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
    interval_keyboard,
    main_menu_keyboard,
    radius_keyboard,
    rule_actions_keyboard,
    rules_list_keyboard,
    sites_select_keyboard,
    skip_cancel_keyboard,
)
from app.bot.states import RuleWizard
from app.bot.texts import t
from app.config.settings import settings
from app.database.models import SearchRule, User
from app.database.models.enums import SiteName
from app.parsers import registry
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
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    text = _render_rule(rule) + await _stats_line(session, rule.id)
    await cb.message.edit_text(text, reply_markup=rule_actions_keyboard(rule, lang))
    await cb.answer()


async def _stats_line(session: AsyncSession, rule_id: int) -> str:
    """Compact 7-day statistics block for the rule view (never raises)."""
    try:
        from app.services.repositories import ListingRepository

        count, avg_price, min_price = await ListingRepository(session).rule_stats(
            rule_id, days=7
        )
    except Exception:  # noqa: BLE001 - stats are decoration, not critical
        return ""
    if count == 0:
        return "\n\n📊 Letzte 7 Tage: noch keine Treffer"
    parts = [f"{count} Angebote"]
    if avg_price:
        parts.append(f"Ø {avg_price:,.0f} €".replace(",", "."))
    if min_price:
        parts.append(f"ab {min_price:,.0f} €".replace(",", "."))
    return "\n\n📊 Letzte 7 Tage: " + " · ".join(parts)


@router.callback_query(F.data.startswith("rule:run:"))
async def cb_run_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    """Run a rule immediately and deliver the results in-chat (great for testing)."""
    rule_id = int(cb.data.split(":")[-1])
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    from app.services.throttle import manual_run_allowed

    wait = await manual_run_allowed(user.telegram_id)
    if wait:
        await cb.answer(f"⏳ Bitte {wait}s warten (Schutz vor Sperren).", show_alert=True)
        return
    await cb.answer("🔍 Suche läuft…")
    status = await cb.message.answer("🔍 Suche läuft, einen Moment…")

    from app.bot.notifier import send_listing_card
    from app.services.search_service import SearchService

    try:
        notable = await SearchService(session).run_rule(rule)
    except Exception as exc:  # noqa: BLE001 - surface the real error to the user
        logger.exception("Manual run of rule {} failed", rule_id)
        from html import escape as _esc

        detail = _esc(f"{type(exc).__name__}: {exc}"[:350])
        await status.edit_text(
            "⚠️ Suche fehlgeschlagen:\n"
            f"<code>{detail}</code>\n\n"
            "Bitte diese Meldung an den Entwickler weitergeben."
        )
        return

    sent = 0
    for row in notable[:5]:
        if await send_listing_card(cb.message.bot, user.telegram_id, row, lang):
            row.notified = True
            sent += 1

    loc_note = await _location_note(rule)
    if notable:
        await status.edit_text(
            f"✅ Fertig: <b>{len(notable)}</b> neue Treffer, {sent} Karte(n) gesendet."
            + loc_note
        )
    else:
        await status.edit_text(
            "😕 Keine neuen Treffer. Entweder gibt es nichts Neues, oder die "
            "Filter sind zu streng (Preis/Ausschlusswörter prüfen)." + loc_note
        )


async def _location_note(rule: SearchRule) -> str:
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
        return f"\n📍 Umkreis aktiv: {place}{radius}"
    return (
        f"\n⚠️ Ort <b>{place}</b> wurde nicht erkannt — es wurde "
        "deutschlandweit gesucht! PLZ prüfen und Suche neu anlegen."
    )


@router.callback_query(F.data.startswith("rule:toggle:"))
async def cb_toggle_rule(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    rule_id = int(cb.data.split(":")[-1])
    repo = SearchRuleRepository(session)
    rule = await repo.get(rule_id, user.id)
    if rule is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    rule.is_active = not rule.is_active
    await session.flush()
    await cb.message.edit_text(_render_rule(rule), reply_markup=rule_actions_keyboard(rule, lang))
    await cb.answer("🟢 Aktiv" if rule.is_active else "⚪️ Pausiert")


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
    await cb.answer("🗑 Gelöscht")


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
    await state.set_state(RuleWizard.name)
    await cb.message.answer(t("rule.ask_name", lang), reply_markup=cancel_keyboard(lang))
    await cb.answer()


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
            "⚠️ Bitte Zahl oder Bereich senden (z. B. 1200 oder 500-1200).",
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
    await _preview_matches(message, state)
    await _ask_location(message, lang, state)


async def _preview_matches(message: Message, state: FSMContext) -> None:
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
    status = await message.answer("🔎 Kurzer Test, wie viele Treffer das gerade gibt…")
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
            "🔎 <b>0 Treffer</b> mit diesen Angaben.\n"
            "Das kann passen (dann kommen nur wirklich neue Anzeigen) — "
            "oder die Suchbegriffe sind zu eng. Ändern geht später jederzeit."
        )
        return

    prices = [p.price for p in parsed if p.price is not None]
    stats = compute_price_stats(prices)
    line = f"🔎 <b>{len(parsed)} Treffer</b> gerade online"
    if stats.median:
        line += f" · Marktpreis ~ <b>{stats.median:,.0f} €</b>".replace(",", ".")
    if prices:
        line += f"\nGünstigstes: {min(prices):,.0f} €".replace(",", ".")
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
    await _ask_sites(cb.message, lang, state)
    await cb.answer()


# --- Platform selection (multi-select) --------------------------------------
@router.callback_query(RuleWizard.sites, F.data.startswith("wizsite:toggle:"))
async def cb_site_toggle(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    site = cb.data.split(":")[-1]
    data = await state.get_data()
    selected = list(data.get("sites", []))
    if site in selected:
        selected.remove(site)
    else:
        selected.append(site)
    await state.update_data(sites=selected)
    await cb.message.edit_reply_markup(
        reply_markup=sites_select_keyboard(_available_sites(), selected, lang)
    )
    await cb.answer()


@router.callback_query(RuleWizard.sites, F.data == "wizsite:all")
async def cb_site_all(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.update_data(sites=[])
    await cb.message.edit_reply_markup(
        reply_markup=sites_select_keyboard(_available_sites(), [], lang)
    )
    await cb.answer(t("btn.all_platforms", lang))


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
    seconds, tier_note = _clamp_interval_for_tier(user, seconds)
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
        await _ask_sites(cb.message, lang, state)
    await cb.answer()


# --- Helpers ----------------------------------------------------------------
def _clamp_interval_for_tier(user: User, seconds: int) -> tuple[int, str | None]:
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
        hint = f" {n.label} prüft ab {n.min_interval_seconds // 60} min — /premium"
    return min_allowed, (
        f"⏱ In deinem Tarif ist das schnellste Intervall "
        f"{min_allowed // 60} min — auf {min_allowed // 60} min gesetzt.{hint}"
    )


def _available_sites() -> list[str]:
    return [s.value for s in registry.available_sites]


async def _ask_location(message: Message, lang: str, state: FSMContext) -> None:
    await state.set_state(RuleWizard.location)
    await message.answer(
        t("rule.ask_location", lang), reply_markup=skip_cancel_keyboard(lang)
    )


async def _ask_sites(message: Message, lang: str, state: FSMContext) -> None:
    await state.set_state(RuleWizard.sites)
    data = await state.get_data()
    selected = list(data.get("sites", []))
    await message.answer(
        t("rule.ask_sites", lang),
        reply_markup=sites_select_keyboard(_available_sites(), selected, lang),
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


def _category_label(slug: str | None) -> str:
    for s, label in CATEGORY_CHOICES:
        if s == slug:
            return label
    return "alle"


def _render_rule(rule: SearchRule) -> str:
    # All user-entered values are HTML-escaped: a rule named "RTX <3000"
    # would otherwise break Telegram's HTML parser on every render.
    state = "🟢 aktiv" if rule.is_active else "⚪️ pausiert"
    if rule.min_price and rule.max_price:
        price = f"{rule.min_price:.0f}–{rule.max_price:.0f} €"
    elif rule.min_price:
        price = f"ab {rule.min_price:.0f} €"
    elif rule.max_price:
        price = f"bis {rule.max_price:.0f} €"
    else:
        price = "beliebig"
    excl = escape(", ".join(rule.exclude_keywords)) if rule.exclude_keywords else "—"
    sites = ", ".join(s.title() for s in rule.sites) if rule.sites else "alle"
    ort = "überall"
    if rule.location:
        ort = escape(rule.location)
        if rule.max_distance_km:
            ort += f" (±{rule.max_distance_km} km)"
    return (
        f"📋 <b>{escape(rule.name)}</b>  ({state})\n\n"
        f"🔎 Suchbegriffe: <code>{escape(rule.keywords)}</code>\n"
        f"📂 Kategorie: {_category_label(rule.category)}\n"
        f"💶 Preis: {price}\n"
        f"🚫 Ausschluss: {excl}\n"
        f"📍 Ort: {ort}\n"
        f"🏪 Plattformen: {sites}\n"
        f"⏱ Intervall: {_interval_label(rule.interval_seconds)}\n"
        f"🎯 Min. Deal-Score: {rule.min_deal_score}"
    )
