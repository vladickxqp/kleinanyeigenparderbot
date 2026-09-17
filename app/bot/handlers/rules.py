"""Search-rule management: list, open, toggle, delete, and creation wizard."""

from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.bot.keyboards import (
    CATEGORY_CHOICES,
    INTERVAL_CHOICES,
    RADIUS_CHOICES,
    cancel_keyboard,
    category_keyboard,
    condition_short,
    draft_confirm_keyboard,
    interval_keyboard,
    main_menu_keyboard,
    radius_keyboard,
    rule_actions_keyboard,
    rules_list_keyboard,
    sentence_keyboard,
    sites_select_keyboard,
    skip_cancel_keyboard,
    vehicle_short,
)
from app.bot.states import RuleWizard
from app.bot.texts import t
from app.config.settings import settings
from app.database.models import SearchRule, User
from app.database.models.enums import Condition, SiteName
from app.parsers import registry
from app.parsers.registry import site_label
from app.services import rule_nlp
from app.services import sites as site_access
from app.services.parsing import parse_price_range
from app.services.repositories import SearchRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="rules")


# --- Listing rules ----------------------------------------------------------
@router.callback_query(F.data == "menu:rules")
async def cb_list_rules(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    rules = await SearchRuleRepository(session).list_for_user(user.id)
    if not rules:
        await cb.message.edit_text(
            t("rule.none", lang), reply_markup=main_menu_keyboard(lang)
        )
    else:
        await cb.message.edit_text(
            t("btn.rules", lang), reply_markup=rules_list_keyboard(rules, lang)
        )
    await cb.answer()


@router.callback_query(F.data.startswith("rule:open:"))
async def cb_open_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    rule_id = int(cb.data.split(":")[-1])
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        await cb.answer(t("edit.not_found", lang), show_alert=True)
        return
    text = _render_rule(rule, lang, user) + await _stats_line(session, rule.id, lang)
    await cb.message.edit_text(text, reply_markup=rule_actions_keyboard(rule, lang))
    await cb.answer()


async def _stats_line(
    session: AsyncSession, rule_id: int, lang: str | None = None
) -> str:
    """Compact 7-day statistics block for the rule view (never raises)."""
    try:
        from app.services.repositories import ListingRepository

        count, avg_price, min_price = await ListingRepository(session).rule_stats(
            rule_id, days=7
        )
    except Exception:  # noqa: BLE001 - stats are decoration, not critical
        return ""
    head = t("rule.stats_head", lang)
    if count == 0:
        return f"\n\n{head}: " + t("rule.stats_empty", lang)
    parts = [t("rule.stats_offers", lang, count=count)]
    if avg_price:
        parts.append(f"Ø {avg_price:,.0f} €".replace(",", "."))
    if min_price:
        amount = f"{min_price:,.0f} €".replace(",", ".")
        parts.append(t("val.price_from", lang, amount=amount))
    return f"\n\n{head}: " + " · ".join(parts)


@router.callback_query(F.data.startswith("rule:run:"))
async def cb_run_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    """Run a rule immediately and deliver the results in-chat (great for testing)."""
    rule_id = int(cb.data.split(":")[-1])
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        await cb.answer(t("edit.not_found", lang), show_alert=True)
        return
    from app.services.throttle import manual_run_allowed

    wait = await manual_run_allowed(user.telegram_id, scope="manual")
    if wait:
        await cb.answer(
            t("rule.run_cooldown", lang, seconds=wait), show_alert=True
        )
        return
    await cb.answer(t("rule.run_started", lang))
    status = await cb.message.answer(t("rule.run_working", lang))

    from app.bot.notifier import send_listing_card
    from app.services.search_service import SearchService

    try:
        notable = await SearchService(session).run_rule(rule)
    except Exception as exc:  # noqa: BLE001 - surface the real error to the user
        logger.exception("Manual run of rule {} failed", rule_id)
        from html import escape as _esc

        detail = _esc(f"{type(exc).__name__}: {exc}"[:350])
        await status.edit_text(t("rule.run_failed", lang, detail=detail))
        return

    sent = 0
    capped = False
    for row in notable[:5]:
        # Same quota and audit trail as the scheduled path: the button must not
        # become a way around the daily card limit.
        if await send_listing_card(
            cb.message.bot, user.telegram_id, row, lang, user=user, session=session
        ):
            row.notified = True
            sent += 1
        elif sent == 0 or capped:
            capped = True
            break
        else:
            capped = True

    loc_note = await _location_note(rule, lang)
    if capped:
        from app.services import quota as quota_svc

        hint = quota_svc.upgrade_hint(quota_svc.KIND_CARDS, user, lang)
        loc_note += t("rule.run_capped", lang) + (
            t("rule.run_capped_hint", lang, hint=hint) if hint else ""
        )
    if notable:
        await status.edit_text(
            t("rule.run_done", lang, found=len(notable), sent=sent) + loc_note
        )
    else:
        await status.edit_text(t("rule.run_empty", lang) + loc_note)


async def _location_note(rule: SearchRule, lang: str | None = None) -> str:
    """Tell the user whether the Kleinanzeigen radius filter is really active."""
    if not (rule.location or rule.zip_code):
        return ""
    parser = registry.get(SiteName.KLEINANZEIGEN)
    if parser is None or not hasattr(parser, "resolve_location_id"):
        return ""
    from app.services.search_service import SearchService

    try:
        loc_id = await parser.resolve_location_id(SearchService._build_query(rule))
    except Exception:  # noqa: BLE001 - diagnostics must never break the flow
        return ""
    place = rule.location or rule.zip_code
    radius = f" ±{rule.max_distance_km} km" if rule.max_distance_km else ""
    if loc_id:
        return t("rule.radius_active", lang, place=f"{place}{radius}")
    return t("rule.radius_unknown", lang, place=place)


@router.callback_query(F.data.startswith("rule:toggle:"))
async def cb_toggle_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    rule_id = int(cb.data.split(":")[-1])
    repo = SearchRuleRepository(session)
    rule = await repo.get(rule_id, user.id)
    if rule is None:
        await cb.answer(t("edit.not_found", lang), show_alert=True)
        return
    rule.is_active = not rule.is_active
    await session.flush()
    await cb.message.edit_text(
        _render_rule(rule, lang, user), reply_markup=rule_actions_keyboard(rule, lang)
    )
    await cb.answer(
        t("rule.toggled_active" if rule.is_active else "rule.toggled_paused", lang)
    )


@router.callback_query(F.data.startswith("rule:delete:"))
async def cb_delete_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    rule_id = int(cb.data.split(":")[-1])
    repo = SearchRuleRepository(session)
    rule = await repo.get(rule_id, user.id)
    if rule is not None:
        await repo.delete(rule)
        await session.flush()
    rules = await repo.list_for_user(user.id)
    if rules:
        await cb.message.edit_text(
            t("btn.rules", lang), reply_markup=rules_list_keyboard(rules, lang)
        )
    else:
        await cb.message.edit_text(
            t("rule.none", lang), reply_markup=main_menu_keyboard(lang)
        )
    await cb.answer(t("rule.deleted", lang))


# --- Creation wizard --------------------------------------------------------
@router.callback_query(F.data == "rule:new")
async def cb_new_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    count = await SearchRuleRepository(session).count_for_user(user.id)
    is_admin = user.telegram_id in settings.admin_ids
    if not is_admin and count >= user.max_rules:
        await cb.answer(
            t("rule.limit_reached", lang, max=user.max_rules), show_alert=True
        )
        return
    if rule_nlp.is_enabled():
        # The eight questions below are where most people stop. One sentence
        # gets to a finished proposal; the wizard stays one tap away.
        await state.set_state(RuleWizard.sentence)
        await cb.message.answer(
            t("rule.ask_sentence", lang), reply_markup=sentence_keyboard(lang)
        )
        await cb.answer()
        return
    await _ask_name(cb.message, lang, state)
    await cb.answer()


@router.callback_query(F.data == "rule:steps")
async def cb_rule_steps(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    """Leave the short path for the full wizard."""
    await _ask_name(cb.message, lang, state)
    await cb.answer()


# --- The short path: one sentence -------------------------------------------
@router.message(RuleWizard.sentence, F.text)
async def wiz_sentence(message: Message, lang: str, state: FSMContext) -> None:
    draft = await rule_nlp.build_draft(message.text or "")
    if not draft.is_usable:
        # Nothing to search for. Say so and keep the field open rather than
        # creating a rule that would quietly match everything.
        await message.answer(
            t("rule.sentence_unclear", lang), reply_markup=sentence_keyboard(lang)
        )
        return
    await state.update_data(draft=draft.as_dict())
    await message.answer(
        _draft_summary(draft, lang), reply_markup=draft_confirm_keyboard(lang)
    )


@router.callback_query(RuleWizard.sentence, F.data == "rule:draft:save")
async def cb_draft_save(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    """Take the proposal as it stands: every platform, the tier's own speed."""
    draft = await _stored_draft(state)
    if draft is None:
        await cb.answer()
        return
    seconds, tier_note = _clamp_interval_for_tier(
        user, settings.scraper_default_interval_seconds, lang
    )
    await _apply_draft(state, draft)
    await _finalize(
        cb.message, user, session, lang, state,
        exclude=list(draft.exclude_keywords),
        sites=[],
        interval_seconds=seconds,
    )
    await cb.answer(tier_note or "", show_alert=bool(tier_note))


@router.callback_query(RuleWizard.sentence, F.data == "rule:draft:adjust")
async def cb_draft_adjust(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    """Keep the sentence, then pick the two things it can never express."""
    draft = await _stored_draft(state)
    if draft is None:
        await cb.answer()
        return
    await _apply_draft(state, draft)
    await _ask_sites(cb.message, lang, state, user)
    await cb.answer()


async def _stored_draft(state: FSMContext) -> rule_nlp.RuleDraft | None:
    """The proposal behind the buttons — re-validated on the way out of storage."""
    data = await state.get_data()
    draft = rule_nlp.RuleDraft.from_dict(data.get("draft"))
    return draft if draft.is_usable else None


async def _apply_draft(state: FSMContext, draft: rule_nlp.RuleDraft) -> None:
    """Move the proposal into the fields the wizard's own finish step reads."""
    await state.update_data(
        name=draft.name,
        keywords=draft.keywords,
        min_price=draft.min_price,
        max_price=draft.max_price,
        exclude=list(draft.exclude_keywords),
        location=draft.location,
        zip_code=draft.zip_code,
        max_distance_km=draft.max_distance_km,
        max_mileage_km=draft.max_mileage_km,
        condition=draft.condition.value,
        category=None,
    )


def _draft_summary(draft: rule_nlp.RuleDraft, lang: str) -> str:
    """What the sentence was understood to mean, in the user's language."""
    if draft.min_price is not None and draft.max_price is not None:
        price = f"{draft.min_price:.0f}–{draft.max_price:.0f} €"
    elif draft.min_price is not None:
        price = t("val.price_from", lang, amount=f"{draft.min_price:.0f} €")
    elif draft.max_price is not None:
        price = t("val.price_upto", lang, amount=f"{draft.max_price:.0f} €")
    else:
        price = t("rule.f_any", lang)

    place = t("rule.f_everywhere", lang)
    if draft.location or draft.zip_code:
        place = escape(draft.location or draft.zip_code or "")
        if draft.max_distance_km:
            place += f" (±{draft.max_distance_km} km)"

    lines = [
        f"{t('rule.sentence_understood', lang)}\n",
        f"<b>{escape(draft.name)}</b>",
        f"🔎 {t('rule.f_keywords', lang)}: <code>{escape(draft.keywords)}</code>",
        f"💶 {t('rule.f_price', lang)}: {escape(price)}",
        f"📍 {t('rule.f_place', lang)}: {place}",
    ]
    if draft.condition is not Condition.ANY:
        lines.append(
            f"🏷 {t('rule.f_condition', lang)}: {condition_short(draft.condition, lang)}"
        )
    if draft.exclude_keywords:
        excluded = ", ".join(escape(word) for word in draft.exclude_keywords)
        lines.append(f"🚫 {t('rule.f_exclude', lang)}: {excluded}")
    if draft.max_mileage_km is not None:
        lines.append(
            f"🚗 {t('rule.f_mileage', lang)}: "
            f"{vehicle_short(draft.max_mileage_km, None, lang)}"
        )
    return "\n".join(lines)


def _stored_condition(value: object) -> Condition:
    """A condition out of FSM storage — an unknown value filters nothing."""
    try:
        return Condition(str(value))
    except ValueError:
        return Condition.ANY


async def _ask_name(message: Message, lang: str, state: FSMContext) -> None:
    await state.set_state(RuleWizard.name)
    await message.answer(t("rule.ask_name", lang), reply_markup=cancel_keyboard(lang))


@router.callback_query(F.data == "wizard:cancel")
async def cb_cancel(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer(
        t("common.cancelled", lang), reply_markup=main_menu_keyboard(lang)
    )
    await cb.answer()


@router.message(RuleWizard.name, F.text)
async def wiz_name(message: Message, lang: str, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip()[:128])
    await state.set_state(RuleWizard.keywords)
    await message.answer(t("rule.ask_keywords", lang), reply_markup=cancel_keyboard(lang))


@router.message(RuleWizard.keywords, F.text)
async def wiz_keywords(message: Message, lang: str, state: FSMContext) -> None:
    await state.update_data(keywords=message.text.strip()[:256])
    await state.set_state(RuleWizard.category)
    await message.answer(
        t("rule.ask_category", lang), reply_markup=category_keyboard(lang)
    )


# --- Category selection -------------------------------------------------------
@router.callback_query(RuleWizard.category, F.data.startswith("wizcat:"))
async def cb_category(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    slug = cb.data.split(":")[-1]
    valid = {s for s, _ in CATEGORY_CHOICES}
    await state.update_data(category=slug if slug in valid else None)
    await state.set_state(RuleWizard.max_price)
    await cb.message.answer(
        t("rule.ask_max_price", lang), reply_markup=skip_cancel_keyboard(lang)
    )
    await cb.answer()


@router.message(RuleWizard.max_price, F.text)
async def wiz_max_price(message: Message, lang: str, state: FSMContext) -> None:
    parsed = parse_price_range(message.text or "")
    if parsed is None:
        await message.answer(
            t("edit.price_invalid", lang),
            reply_markup=skip_cancel_keyboard(lang),
        )
        return
    min_price, max_price = parsed
    await state.update_data(min_price=min_price, max_price=max_price)
    await state.set_state(RuleWizard.exclude)
    await message.answer(
        t("rule.ask_exclude", lang), reply_markup=skip_cancel_keyboard(lang)
    )


@router.message(RuleWizard.exclude, F.text)
async def wiz_exclude(
    message: Message, lang: str, state: FSMContext
) -> None:
    excludes = [w.strip() for w in (message.text or "").split(",") if w.strip()]
    await state.update_data(exclude=excludes)
    await _preview_matches(message, state, lang)
    await _ask_location(message, lang, state)


async def _preview_matches(
    message: Message, state: FSMContext, lang: str | None = None
) -> None:
    """Show how many offers the criteria hit right now.

    The wizard asks eight questions before the user sees a single result. One
    quick look at the current hit count and price range tells them whether the
    keywords are any good, while it is still cheap to change them.
    """
    data = await state.get_data()
    keywords = (data.get("keywords") or "").strip()
    if not keywords:
        return

    from app.parsers import registry
    from app.parsers.schemas import SearchQuery
    from app.services.price_analysis import compute_price_stats
    from app.services.relevance import filter_relevant

    query = SearchQuery(
        keywords=keywords[:256],
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        exclude_keywords=list(data.get("exclude", [])),
        max_results=40,
    )
    status = await message.answer(t("rule.preview_testing", lang))
    try:
        parsers = [p for p in registry if not p.requires_browser]
        results = await asyncio.gather(
            *(p.collect(query) for p in parsers), return_exceptions=True
        )
        parsed = []
        for res in results:
            if not isinstance(res, BaseException):
                parsed.extend(res)
        parsed = filter_relevant(query, parsed)
    except Exception as exc:  # noqa: BLE001 - a preview must never block the wizard
        logger.debug("Wizard preview failed: {}", exc)
        await status.delete()
        return

    if not parsed:
        await status.edit_text(
            t("rule.preview_none", lang) + t("rule.preview_none_hint", lang)
        )
        return

    prices = [p.price for p in parsed if p.price is not None]
    stats = compute_price_stats(prices)
    line = t("rule.preview_found", lang, count=len(parsed))
    if stats.median:
        line += f" · Marktpreis ~ <b>{stats.median:,.0f} €</b>".replace(",", ".")
    if prices:
        cheapest = f"{min(prices):,.0f} €".replace(",", ".")
        line += t("rule.preview_cheapest", lang, amount=cheapest)
    await status.edit_text(line + "\n\nWeiter geht's 👇")


# --- Location + radius ---------------------------------------------------------
@router.message(RuleWizard.location, F.text)
async def wiz_location(message: Message, lang: str, state: FSMContext) -> None:
    term = (message.text or "").strip()[:64]
    zip_code = term if term.isdigit() and 4 <= len(term) <= 5 else None
    await state.update_data(location=term, zip_code=zip_code)
    await state.set_state(RuleWizard.radius)
    await message.answer(t("rule.ask_radius", lang), reply_markup=radius_keyboard(lang))


@router.callback_query(RuleWizard.radius, F.data.startswith("wizrad:"))
async def cb_radius(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    try:
        km = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    if km not in RADIUS_CHOICES:
        km = RADIUS_CHOICES[-1]
    await state.update_data(max_distance_km=km)
    await _ask_sites(cb.message, lang, state, user)
    await cb.answer()


# --- Platform selection (multi-select) --------------------------------------
@router.callback_query(RuleWizard.sites, F.data.startswith("wizsite:toggle:"))
async def cb_site_toggle(
    cb: CallbackQuery, user: User, lang: str, state: FSMContext
) -> None:
    site = cb.data.split(":")[-1]
    data = await state.get_data()
    selected = list(data.get("sites", []))
    cap = site_access.cap_for(user)

    if site in selected:
        selected.remove(site)
    elif cap >= 0 and len(selected) >= cap:
        # The cap is spent. Say what the extra platform costs instead of
        # letting the box refuse to tick for no visible reason.
        level = site_access.upgrade_level(user)
        await cb.answer(
            t("rule.sites_locked", lang, level=level) if level else "",
            show_alert=bool(level),
        )
        return
    else:
        selected.append(site)

    await state.update_data(sites=selected)
    await cb.message.edit_reply_markup(
        reply_markup=sites_select_keyboard(
            _available_sites(), selected, lang, max_sites=cap
        )
    )
    await cb.answer()


@router.callback_query(RuleWizard.sites, F.data == "wizsite:all")
async def cb_site_all(
    cb: CallbackQuery, user: User, lang: str, state: FSMContext
) -> None:
    cap = site_access.cap_for(user)
    if cap < 0:
        # No cap: the empty list keeps meaning "every marketplace we have",
        # including ones added after this rule was written.
        await state.update_data(sites=[])
        await cb.message.edit_reply_markup(
            reply_markup=sites_select_keyboard(_available_sites(), [], lang)
        )
        await cb.answer(t("btn.all_platforms", lang))
        return

    # Capped: store what they actually get, so the rule never claims "all".
    granted = [s.value for s in site_access.resolve(None, user)]
    await state.update_data(sites=granted)
    await cb.message.edit_reply_markup(
        reply_markup=sites_select_keyboard(
            _available_sites(), granted, lang, max_sites=cap
        )
    )
    level = site_access.upgrade_level(user)
    names = ", ".join(site_label(s) for s in granted)
    await cb.answer(
        t("rule.sites_all_capped", lang, site=names, level=level) if level else names,
        show_alert=bool(level),
    )


@router.callback_query(RuleWizard.sites, F.data == "wizsite:done")
async def cb_site_done(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.set_state(RuleWizard.interval)
    await cb.message.answer(
        t("rule.ask_interval", lang), reply_markup=interval_keyboard(lang)
    )
    await cb.answer()


# --- Interval selection -------------------------------------------------------
@router.callback_query(RuleWizard.interval, F.data.startswith("wizint:"))
async def cb_interval(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    try:
        seconds = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    # Only accept the offered choices; anything else falls back to the default.
    if seconds not in {s for s, _ in INTERVAL_CHOICES}:
        seconds = settings.scraper_default_interval_seconds
    seconds, tier_note = _clamp_interval_for_tier(user, seconds, lang)
    data = await state.get_data()
    await _finalize(
        cb.message,
        user,
        session,
        lang,
        state,
        exclude=list(data.get("exclude", [])),
        sites=list(data.get("sites", [])),
        interval_seconds=seconds,
    )
    if tier_note:
        await cb.answer(tier_note, show_alert=True)
    else:
        await cb.answer()


# --- Skip handling for optional steps ---------------------------------------
@router.callback_query(F.data == "wizard:skip")
async def cb_skip(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    current = await state.get_state()
    if current == RuleWizard.max_price.state:
        await state.set_state(RuleWizard.exclude)
        await cb.message.answer(
            t("rule.ask_exclude", lang), reply_markup=skip_cancel_keyboard(lang)
        )
    elif current == RuleWizard.exclude.state:
        await state.update_data(exclude=[])
        await _ask_location(cb.message, lang, state)
    elif current == RuleWizard.location.state:
        await _ask_sites(cb.message, lang, state, user)
    await cb.answer()


# --- Helpers ----------------------------------------------------------------
def _clamp_interval_for_tier(
    user: User, seconds: int, lang: str | None = None
) -> tuple[int, str | None]:
    """Enforce the tier's minimum check interval (admins are exempt).

    Returns the effective interval and an optional user-facing note.
    """
    if user.telegram_id in settings.admin_ids:
        return seconds, None
    min_allowed = user.min_interval_seconds
    if seconds >= min_allowed:
        return seconds, None
    from app.services import entitlements as ent

    nxt = ent.next_tier(user.subscription)
    hint = ""
    if nxt is not None:
        n = ent.for_tier(nxt)
        hint = t(
            "rule.tier_interval_hint", lang,
            label=n.label, minutes=n.min_interval_seconds // 60,
        )
    return min_allowed, t(
        "rule.tier_interval", lang, minutes=min_allowed // 60, hint=hint
    )


def _available_sites() -> list[str]:
    return [s.value for s in registry.available_sites]


async def _ask_location(message: Message, lang: str, state: FSMContext) -> None:
    await state.set_state(RuleWizard.location)
    await message.answer(
        t("rule.ask_location", lang), reply_markup=skip_cancel_keyboard(lang)
    )


async def _ask_sites(
    message: Message, lang: str, state: FSMContext, user: User | None = None
) -> None:
    await state.set_state(RuleWizard.sites)
    data = await state.get_data()
    selected = list(data.get("sites", []))
    cap = site_access.cap_for(user)
    text = t("rule.ask_sites", lang)
    level = site_access.upgrade_level(user)
    if level:
        # Said before the first tap, not after it: the cap is part of the
        # question, not a surprise on the answer.
        text += "\n\n" + t("rule.sites_capped", lang, level=level)
    await message.answer(
        text,
        reply_markup=sites_select_keyboard(
            _available_sites(), selected, lang, max_sites=cap
        ),
    )


async def _finalize(
    message: Message,
    user: User,
    session: AsyncSession,
    lang: str,
    state: FSMContext,
    *,
    exclude: list[str],
    sites: list[str] | None = None,
    interval_seconds: int | None = None,
) -> None:
    data = await state.get_data()
    await state.clear()
    rule = SearchRule(
        user_id=user.id,
        name=data.get("name", "Suche"),
        keywords=data.get("keywords", ""),
        exclude_keywords=exclude,
        category=data.get("category"),
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        location=data.get("location"),
        zip_code=data.get("zip_code"),
        max_distance_km=data.get("max_distance_km"),
        max_mileage_km=data.get("max_mileage_km"),
        # Only the sentence path can set these; the step-by-step wizard leaves
        # them to the edit menu, which is why the fallbacks are "unfiltered".
        condition=_stored_condition(data.get("condition")),
        interval_seconds=interval_seconds or settings.scraper_default_interval_seconds,
        sites=sites or [],  # empty = all registered parsers
    )
    await SearchRuleRepository(session).add(rule)
    await session.flush()
    await message.answer(
        t("rule.created", lang, name=escape(rule.name)),
        reply_markup=main_menu_keyboard(lang),
    )


def _interval_label(seconds: int) -> str:
    for s, label in INTERVAL_CHOICES:
        if s == seconds:
            return label
    return f"{seconds}s"


def _category_label(slug: str | None, lang: str | None = None) -> str:
    for s, key in CATEGORY_CHOICES:
        if s == slug:
            return t(key, lang)
    return t("rule.f_all", lang)


def _render_rule(
    rule: SearchRule, lang: str | None = None, owner: User | None = None
) -> str:
    # All user-entered values are HTML-escaped: a rule named "RTX <3000"
    # would otherwise break Telegram's HTML parser on every render.
    state = t("rule.state_active" if rule.is_active else "rule.state_paused", lang)
    if rule.min_price and rule.max_price:
        price = f"{rule.min_price:.0f}–{rule.max_price:.0f} €"
    elif rule.min_price:
        price = t("val.price_from", lang, amount=f"{rule.min_price:.0f} €")
    elif rule.max_price:
        price = t("val.price_upto", lang, amount=f"{rule.max_price:.0f} €")
    else:
        price = t("rule.f_any", lang)
    excl = (
        escape(", ".join(rule.exclude_keywords))
        if rule.exclude_keywords
        else t("rule.f_none", lang)
    )
    # What the rule really searches, after the owner's level — plus what an
    # upgrade would add. "alle" on a capped rule would simply be untrue.
    searched = site_access.resolve(rule.sites, owner)
    sites = ", ".join(site_label(s) for s in searched) or t("rule.f_all", lang)
    missing = site_access.withheld(rule.sites, owner)
    if missing:
        level = site_access.upgrade_level(owner)
        if level:
            sites += t("rule.f_sites_more", lang, count=len(missing), level=level)
    ort = t("rule.f_everywhere", lang)
    if rule.location:
        ort = escape(rule.location)
        if rule.max_distance_km:
            ort += f" (±{rule.max_distance_km} km)"
    lines = [
        f"📋 <b>{escape(rule.name)}</b>  ({state})\n",
        f"🔎 {t('rule.f_keywords', lang)}: <code>{escape(rule.keywords)}</code>",
        f"📂 {t('rule.f_category', lang)}: {_category_label(rule.category, lang)}",
        f"💶 {t('rule.f_price', lang)}: {price}",
        f"🚫 {t('rule.f_exclude', lang)}: {excl}",
        f"📍 {t('rule.f_place', lang)}: {ort}",
    ]
    # Only for a rule that actually set them: on a phone hunt the line would
    # be noise, and the card is already long.
    if rule.max_mileage_km is not None or rule.min_year is not None:
        bounds = vehicle_short(rule.max_mileage_km, rule.min_year, lang)
        lines.append(f"🚗 {t('rule.f_vehicle', lang)}: {bounds}")
    lines += [
        f"🏪 {t('rule.f_sites', lang)}: {sites}",
        f"⏱ {t('rule.f_interval', lang)}: {_interval_label(rule.interval_seconds)}",
        f"🎯 {t('rule.f_minscore', lang)}: {rule.min_deal_score}",
    ]
    return "\n".join(lines)
