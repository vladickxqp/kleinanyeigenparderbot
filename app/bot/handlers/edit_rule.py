"""Edit individual fields of an existing search rule.

Entry point is the "✏️ Bearbeiten" button on a rule; each field opens a small
FSM interaction (the rule id is carried in the FSM data as ``edit_rule_id``).
Sending ``-`` clears optional fields (exclude words, location).

Zustand / Versand / Auktionen live here and nowhere else: they need the paid
``rule_power`` capability, and the creation wizard is already eight questions
long before a user sees a single result.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.rules import _render_rule
from app.bot.keyboards import (
    AUCTION_VALUES,
    CATEGORY_CHOICES,
    CONDITION_CHOICES,
    INTERVAL_CHOICES,
    RADIUS_CHOICES,
    SHIPPING_VALUES,
    auction_short,
    auctions_keyboard,
    cancel_keyboard,
    category_keyboard,
    condition_keyboard,
    condition_short,
    interval_keyboard,
    radius_keyboard,
    rule_actions_keyboard,
    rule_edit_keyboard,
    shipping_keyboard,
    shipping_short,
)
from app.bot.states import EditWizard
from app.bot.texts import t
from app.config.settings import settings
from app.database.models import SearchRule, User
from app.database.models.enums import Condition
from app.services import entitlements as ent
from app.services.parsing import parse_price_range, parse_vehicle_bounds
from app.services.repositories import SearchRuleRepository

router = Router(name="edit_rule")

#: Marker the user sends to clear an optional field.
CLEAR_MARKER = "-"

#: Edit-menu fields that need the paid "rule_power" capability.
POWER_FIELDS: frozenset[str] = frozenset({"condition", "shipping", "auctions"})

#: Longest rule id we pass on to the database. Callback data is user-controlled
#: and a 40-digit number would blow up the BIGINT column, not return "not found".
_MAX_ID_DIGITS = 18


# --- Paid filters: gate + upsell copy -------------------------------------------
def _has_rule_power(user: User) -> bool:
    """Admins get the paid filters so they can test them without a plan."""
    if user.telegram_id in settings.admin_ids:
        return True
    return user.has_feature(ent.FEATURE_RULE_POWER)


def _rule_power_level() -> str:
    """Label of the cheapest level that unlocks the filters (config-driven)."""
    tiers = ent.all_tiers()
    for tier in tiers:
        if tier.has(ent.FEATURE_RULE_POWER):
            return tier.label
    return tiers[-1].label


def _rule_power_pitch(lang: str) -> str:
    """HTML block for the edit menu — what the upgrade actually buys."""
    return t("edit.power_pitch", lang, level=_rule_power_level())


def _rule_power_alert(lang: str) -> str:
    """Plain one-liner — Telegram alerts render no HTML and are short."""
    return t("edit.power_alert", lang, level=_rule_power_level())


# --- Menu ---------------------------------------------------------------------
@router.callback_query(F.data.startswith("rule:edit:"))
async def cb_edit_menu(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    rule_id = int(cb.data.split(":")[-1])
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        await cb.answer(t("edit.not_found", lang), show_alert=True)
        return
    from html import escape

    power = _has_rule_power(user)
    text = t("edit.menu", lang, name=escape(rule.name))
    if not power:
        text += _rule_power_pitch(lang)
    await cb.message.edit_text(
        text, reply_markup=rule_edit_keyboard(rule, lang, has_rule_power=power)
    )
    await cb.answer()


# --- Field dispatch -------------------------------------------------------------
@router.callback_query(F.data.startswith("edit:"))
async def cb_edit_field(
    cb: CallbackQuery, user: User, lang: str, state: FSMContext
) -> None:
    parts = (cb.data or "").split(":")
    field, raw_id = (parts[1], parts[2]) if len(parts) == 3 else ("", "")
    # str.isdigit() also accepts superscripts and other unicode digits that
    # int() then rejects, so the check has to be ASCII-only.
    if not field or not (raw_id.isascii() and raw_id.isdecimal()):
        await cb.answer()
        return
    if len(raw_id) > _MAX_ID_DIGITS:
        await cb.answer()
        return

    # The keyboard hides the paid filters, but callback data is user-controlled:
    # the entitlement decides, not the button that was tapped.
    if (field in POWER_FIELDS or field == "locked") and not _has_rule_power(user):
        await cb.answer(_rule_power_alert(lang), show_alert=True)
        return

    await state.update_data(edit_rule_id=int(raw_id))

    if field == "name":
        await state.set_state(EditWizard.name)
        await cb.message.answer(t("rule.ask_name", lang), reply_markup=cancel_keyboard(lang))
    elif field == "keywords":
        await state.set_state(EditWizard.keywords)
        await cb.message.answer(t("rule.ask_keywords", lang), reply_markup=cancel_keyboard(lang))
    elif field == "category":
        await state.set_state(EditWizard.category)
        await cb.message.answer(t("rule.ask_category", lang), reply_markup=category_keyboard(lang))
    elif field == "price":
        await state.set_state(EditWizard.price)
        await cb.message.answer(t("rule.ask_max_price", lang), reply_markup=cancel_keyboard(lang))
    elif field == "exclude":
        await state.set_state(EditWizard.exclude)
        await cb.message.answer(
            t("rule.ask_exclude", lang) + f"\n(<code>{CLEAR_MARKER}</code> = leeren)",
            reply_markup=cancel_keyboard(lang),
        )
    elif field == "location":
        await state.set_state(EditWizard.location)
        await cb.message.answer(
            t("rule.ask_location", lang) + f"\n(<code>{CLEAR_MARKER}</code> = Ort entfernen)",
            reply_markup=cancel_keyboard(lang),
        )
    elif field == "interval":
        await state.set_state(EditWizard.interval)
        await cb.message.answer(t("rule.ask_interval", lang), reply_markup=interval_keyboard(lang))
    elif field == "minscore":
        await state.set_state(EditWizard.min_score)
        await cb.message.answer(t("edit.ask_minscore", lang), reply_markup=cancel_keyboard(lang))
    elif field == "vehicle":
        await state.set_state(EditWizard.vehicle)
        await cb.message.answer(
            t("edit.ask_vehicle", lang, clear=CLEAR_MARKER),
            reply_markup=cancel_keyboard(lang),
        )
    elif field == "condition":
        await state.set_state(EditWizard.condition)
        await cb.message.answer(
            t("edit.ask_condition", lang), reply_markup=condition_keyboard(lang)
        )
    elif field == "shipping":
        await state.set_state(EditWizard.shipping)
        await cb.message.answer(
            t("edit.ask_shipping", lang), reply_markup=shipping_keyboard(lang)
        )
    elif field == "auctions":
        await state.set_state(EditWizard.auctions)
        await cb.message.answer(
            t("edit.ask_auctions", lang), reply_markup=auctions_keyboard(lang)
        )
    await cb.answer()


# --- Shared helpers -------------------------------------------------------------
async def _load_rule(
    session: AsyncSession, state: FSMContext, user: User
) -> SearchRule | None:
    data = await state.get_data()
    rule_id = data.get("edit_rule_id")
    if rule_id is None:
        return None
    return await SearchRuleRepository(session).get(int(rule_id), user.id)


async def _finish(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    rule: SearchRule,
    lang: str,
    note: str | None = None,
) -> None:
    await session.flush()
    await state.clear()
    # The rule card has no line for the filter fields, so the confirmation is
    # the only place the new value is ever shown back to the user.
    await message.answer(t("edit.saved", lang) + (f"\n{note}" if note else ""))
    await message.answer(
        _render_rule(rule, lang, user), reply_markup=rule_actions_keyboard(rule, lang)
    )


# --- Text-field handlers ---------------------------------------------------------
@router.message(EditWizard.name, F.text)
async def edit_name(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        return
    rule.name = message.text.strip()[:128]
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.keywords, F.text)
async def edit_keywords(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        return
    rule.keywords = message.text.strip()[:256]
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.price, F.text)
async def edit_price(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    parsed = parse_price_range(message.text or "")
    if parsed is None:
        await message.answer(
            t("edit.price_invalid", lang),
            reply_markup=cancel_keyboard(lang),
        )
        return
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        return
    rule.min_price, rule.max_price = parsed
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.vehicle, F.text)
async def edit_vehicle(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if raw == CLEAR_MARKER:
        bounds: tuple[int | None, int | None] | None = (None, None)
    else:
        bounds = parse_vehicle_bounds(raw)
    if bounds is None:
        await message.answer(
            t("edit.vehicle_invalid", lang), reply_markup=cancel_keyboard(lang)
        )
        return
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        return
    rule.max_mileage_km, rule.min_year = bounds
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.exclude, F.text)
async def edit_exclude(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        return
    raw = (message.text or "").strip()
    if raw == CLEAR_MARKER:
        rule.exclude_keywords = []
    else:
        rule.exclude_keywords = [w.strip() for w in raw.split(",") if w.strip()]
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.min_score, F.text)
async def edit_min_score(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    try:
        score = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Bitte eine Zahl 0–100 senden.", reply_markup=cancel_keyboard(lang))
        return
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        return
    rule.min_deal_score = max(0, min(100, score))
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.location, F.text)
async def edit_location(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        return
    term = (message.text or "").strip()[:64]
    if term == CLEAR_MARKER:
        rule.location = None
        rule.zip_code = None
        rule.max_distance_km = None
        await _finish(message, session, state, rule, lang)
        return
    rule.location = term
    rule.zip_code = term if term.isdigit() and 4 <= len(term) <= 5 else None
    await state.set_state(EditWizard.radius)
    await message.answer(t("rule.ask_radius", lang), reply_markup=radius_keyboard(lang))


# --- Inline-choice handlers -------------------------------------------------------
@router.callback_query(EditWizard.radius, F.data.startswith("wizrad:"))
async def edit_radius(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        await cb.answer()
        return
    try:
        km = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    rule.max_distance_km = km if km in RADIUS_CHOICES else RADIUS_CHOICES[-1]
    await _finish(cb.message, session, state, rule, lang)
    await cb.answer()


@router.callback_query(EditWizard.category, F.data.startswith("wizcat:"))
async def edit_category(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        await cb.answer()
        return
    slug = cb.data.split(":")[-1]
    valid = {s for s, _ in CATEGORY_CHOICES}
    rule.category = slug if slug in valid else None
    await _finish(cb.message, session, state, rule, lang)
    await cb.answer()


@router.callback_query(EditWizard.interval, F.data.startswith("wizint:"))
async def edit_interval(
    cb: CallbackQuery,
    user: "User",
    session: AsyncSession,
    lang: str,
    state: FSMContext,
) -> None:
    from app.bot.handlers.rules import _clamp_interval_for_tier

    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        await cb.answer()
        return
    try:
        seconds = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    tier_note = None
    if seconds in {s for s, _ in INTERVAL_CHOICES}:
        seconds, tier_note = _clamp_interval_for_tier(user, seconds, lang)
        rule.interval_seconds = seconds
    await _finish(cb.message, session, state, rule, lang)
    if tier_note:
        await cb.answer(tier_note, show_alert=True)
    else:
        await cb.answer()


# --- Paid filters ---------------------------------------------------------------
async def _load_for_power_edit(
    cb: CallbackQuery, user: User, session: AsyncSession, state: FSMContext,
    lang: str | None = None,
) -> SearchRule | None:
    """Load the rule for a paid-filter edit, or end the interaction."""
    if not _has_rule_power(user):
        await state.clear()
        await cb.answer(_rule_power_alert(lang), show_alert=True)
        return None
    rule = await _load_rule(session, state, user)
    if rule is None:
        await state.clear()
        await cb.answer()
    return rule


@router.callback_query(EditWizard.condition, F.data.startswith("wizcond:"))
async def edit_condition(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_for_power_edit(cb, user, session, state, lang)
    if rule is None:
        return
    slug = cb.data.split(":")[-1]
    if slug not in {s for s, _ in CONDITION_CHOICES}:
        await cb.answer()
        return
    try:
        rule.condition = Condition(slug)
    except ValueError:  # UI choice no longer exists in the enum
        await cb.answer()
        return
    await _finish(
        cb.message, session, state, rule, lang,
        note=t("btn.edit_condition", lang, value=condition_short(rule.condition, lang)),
    )
    await cb.answer()


@router.callback_query(EditWizard.shipping, F.data.startswith("wizship:"))
async def edit_shipping(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_for_power_edit(cb, user, session, state, lang)
    if rule is None:
        return
    slug = cb.data.split(":")[-1]
    if slug not in SHIPPING_VALUES:
        await cb.answer()
        return
    rule.shipping_available = SHIPPING_VALUES[slug]
    await _finish(
        cb.message, session, state, rule, lang,
        note=t("btn.edit_shipping", lang,
               value=shipping_short(rule.shipping_available, lang)),
    )
    await cb.answer()


@router.callback_query(EditWizard.auctions, F.data.startswith("wizauc:"))
async def edit_auctions(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_for_power_edit(cb, user, session, state, lang)
    if rule is None:
        return
    slug = cb.data.split(":")[-1]
    if slug not in AUCTION_VALUES:
        await cb.answer()
        return
    rule.exclude_auctions = AUCTION_VALUES[slug]
    await _finish(
        cb.message, session, state, rule, lang,
        note=t("btn.edit_auctions", lang, value=auction_short(rule.exclude_auctions, lang)),
    )
    await cb.answer()
