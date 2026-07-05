"""Edit individual fields of an existing search rule.

Entry point is the "✏️ Bearbeiten" button on a rule; each field opens a small
FSM interaction (the rule id is carried in the FSM data as ``edit_rule_id``).
Sending ``-`` clears optional fields (exclude words, location).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.rules import _render_rule
from app.bot.keyboards import (
    CATEGORY_CHOICES,
    INTERVAL_CHOICES,
    RADIUS_CHOICES,
    cancel_keyboard,
    category_keyboard,
    interval_keyboard,
    radius_keyboard,
    rule_actions_keyboard,
    rule_edit_keyboard,
)
from app.bot.states import EditWizard
from app.bot.texts import t
from app.database.models import SearchRule
from app.services.parsing import parse_price_range
from app.services.repositories import SearchRuleRepository

router = Router(name="edit_rule")

#: Marker the user sends to clear an optional field.
CLEAR_MARKER = "-"


# --- Menu ---------------------------------------------------------------------
@router.callback_query(F.data.startswith("rule:edit:"))
async def cb_edit_menu(cb: CallbackQuery, session: AsyncSession, lang: str) -> None:
    rule_id = int(cb.data.split(":")[-1])
    rule = await SearchRuleRepository(session).get(rule_id)
    if rule is None:
        await cb.answer("Nicht gefunden", show_alert=True)
        return
    from html import escape

    await cb.message.edit_text(
        t("edit.menu", lang, name=escape(rule.name)),
        reply_markup=rule_edit_keyboard(rule, lang),
    )
    await cb.answer()


# --- Field dispatch -------------------------------------------------------------
@router.callback_query(F.data.startswith("edit:"))
async def cb_edit_field(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    _, field, raw_id = cb.data.split(":")
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
    await cb.answer()


# --- Shared helpers -------------------------------------------------------------
async def _load_rule(session: AsyncSession, state: FSMContext) -> SearchRule | None:
    data = await state.get_data()
    rule_id = data.get("edit_rule_id")
    if rule_id is None:
        return None
    return await SearchRuleRepository(session).get(int(rule_id))


async def _finish(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    rule: SearchRule,
    lang: str,
) -> None:
    await session.flush()
    await state.clear()
    await message.answer(t("edit.saved", lang))
    await message.answer(_render_rule(rule), reply_markup=rule_actions_keyboard(rule, lang))


# --- Text-field handlers ---------------------------------------------------------
@router.message(EditWizard.name, F.text)
async def edit_name(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state)
    if rule is None:
        await state.clear()
        return
    rule.name = message.text.strip()[:128]
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.keywords, F.text)
async def edit_keywords(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state)
    if rule is None:
        await state.clear()
        return
    rule.keywords = message.text.strip()[:256]
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.price, F.text)
async def edit_price(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    parsed = parse_price_range(message.text or "")
    if parsed is None:
        await message.answer(
            "⚠️ Bitte Zahl oder Bereich senden (z. B. 1200 oder 500-1200).",
            reply_markup=cancel_keyboard(lang),
        )
        return
    rule = await _load_rule(session, state)
    if rule is None:
        await state.clear()
        return
    rule.min_price, rule.max_price = parsed
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.exclude, F.text)
async def edit_exclude(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state)
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
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    try:
        score = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Bitte eine Zahl 0–100 senden.", reply_markup=cancel_keyboard(lang))
        return
    rule = await _load_rule(session, state)
    if rule is None:
        await state.clear()
        return
    rule.min_deal_score = max(0, min(100, score))
    await _finish(message, session, state, rule, lang)


@router.message(EditWizard.location, F.text)
async def edit_location(
    message: Message, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state)
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
    cb: CallbackQuery, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state)
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
    cb: CallbackQuery, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state)
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
    cb: CallbackQuery, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    rule = await _load_rule(session, state)
    if rule is None:
        await state.clear()
        await cb.answer()
        return
    try:
        seconds = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer()
        return
    if seconds in {s for s, _ in INTERVAL_CHOICES}:
        rule.interval_seconds = seconds
    await _finish(cb.message, session, state, rule, lang)
    await cb.answer()
