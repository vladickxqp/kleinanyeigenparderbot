"""Broadcast 2.0 (ADMIN+): media, buttons, audience, preview, scheduling.

/broadcast <text>       → quick text broadcast to everyone (legacy, still works)
/broadcast              → wizard: message (text/photo/video/document) →
                          audience → optional URL button → time → PREVIEW → send
/broadcasts             → recent broadcasts with live stats, cancel scheduled

Delivery runs in the worker (rate-limited, progress + final report in this
chat); the bot only records the job — it never blocks on thousands of sends.
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BroadcastAudience, BroadcastStatus, User, UserRole
from app.services import broadcasts as bc_svc
from app.services.roles import has_role

router = Router(name="broadcast")


class BroadcastWizard(StatesGroup):
    content = State()
    audience = State()
    button = State()
    when = State()
    custom_time = State()
    confirm = State()


# --- helpers ------------------------------------------------------------------------
def _button_markup(text: str | None, url: str | None) -> InlineKeyboardMarkup | None:
    if not text or not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


def _audience_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Alle", callback_data="bc:aud:all")
    kb.button(text="🆓 Nur Free", callback_data="bc:aud:free")
    kb.button(text="💎 Nur Premium", callback_data="bc:aud:premium")
    kb.button(text="✖️ Abbrechen", callback_data="bc:cancel")
    kb.adjust(3, 1)
    return kb.as_markup()


def _when_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Jetzt senden", callback_data="bc:when:now")
    kb.button(text="⏰ In 1 Std", callback_data="bc:when:1h")
    kb.button(text="⏰ In 3 Std", callback_data="bc:when:3h")
    kb.button(text="🌅 Morgen 09:00", callback_data="bc:when:tomorrow9")
    kb.button(text="✍️ Zeit eingeben", callback_data="bc:when:custom")
    kb.button(text="✖️ Abbrechen", callback_data="bc:cancel")
    kb.adjust(1, 2, 2, 1)
    return kb.as_markup()


def _confirm_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Senden", callback_data="bc:confirm")
    kb.button(text="✖️ Abbrechen", callback_data="bc:cancel")
    kb.adjust(2)
    return kb.as_markup()


async def _list_text(session: AsyncSession) -> str:
    items = await bc_svc.recent_broadcasts(session)
    if not items:
        return (
            "📢 <b>Broadcasts</b>\n\nNoch keine. Starten mit /broadcast "
            "(Assistent) oder <code>/broadcast Text</code>."
        )
    lines = ["📢 <b>Broadcasts</b>\n"] + [bc_svc.summary_line(b) for b in items]
    lines.append("\nNeu: /broadcast · Geplante abbrechen: Buttons unten")
    return "\n".join(lines)


def _list_keyboard(items) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in items:
        if b.status is BroadcastStatus.SCHEDULED:
            kb.button(text=f"✖️ #{b.id} abbrechen", callback_data=f"bc:cancel_sched:{b.id}")
    kb.button(text="📢 Neuer Broadcast", callback_data="bc:new")
    kb.adjust(1)
    return kb.as_markup()


# --- entry points ---------------------------------------------------------------------
@router.message(Command("broadcast"))
async def cmd_broadcast(
    message: Message, user: User, session: AsyncSession,
    command: CommandObject, state: FSMContext,
) -> None:
    if not has_role(user, UserRole.ADMIN):
        return
    text = (command.args or "").strip()
    if text:
        # Legacy quick path: plain text to everyone, right now.
        status = await message.answer("📢 Broadcast wird gestartet…")
        await bc_svc.create_broadcast(
            session, created_by=user.telegram_id, audience=BroadcastAudience.ALL,
            preview=text, text=f"📢 {escape(text)}",
            status_chat_id=message.chat.id, status_message_id=status.message_id,
        )
        logger.info("ADMIN: {} queued a quick broadcast", user.telegram_id)
        return
    await _start_wizard(message, state)


@router.callback_query(F.data == "bc:new")
async def cb_new(cb: CallbackQuery, user: User, state: FSMContext) -> None:
    if not has_role(user, UserRole.ADMIN):
        await cb.answer("⛔", show_alert=True)
        return
    await _start_wizard(cb.message, state)
    await cb.answer()


async def _start_wizard(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BroadcastWizard.content)
    await message.answer(
        "📢 <b>Neuer Broadcast</b>\n\n"
        "Schick mir jetzt die Nachricht — <b>Text, Foto, Video oder Dokument</b> "
        "(gern mit Bildunterschrift). Formatierung bleibt erhalten, du siehst "
        "vor dem Senden eine Vorschau.\n\n/cancel zum Abbrechen"
    )


@router.message(Command("broadcasts"))
async def cmd_broadcasts(message: Message, user: User, session: AsyncSession) -> None:
    if not has_role(user, UserRole.ADMIN):
        return
    items = await bc_svc.recent_broadcasts(session)
    await message.answer(await _list_text(session), reply_markup=_list_keyboard(items))


@router.callback_query(F.data.startswith("bc:cancel_sched:"))
async def cb_cancel_scheduled(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not has_role(user, UserRole.ADMIN):
        await cb.answer("⛔", show_alert=True)
        return
    ok = await bc_svc.cancel_scheduled(session, int(cb.data.split(":")[-1]))
    items = await bc_svc.recent_broadcasts(session)
    await cb.message.edit_text(await _list_text(session), reply_markup=_list_keyboard(items))
    await cb.answer("✖️ Abgebrochen" if ok else "Nicht mehr abbrechbar")


# --- wizard steps -----------------------------------------------------------------------
@router.message(StateFilter(BroadcastWizard), Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✖️ Broadcast abgebrochen.")


@router.callback_query(F.data == "bc:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("✖️ Broadcast abgebrochen.")
    await cb.answer()


@router.message(
    BroadcastWizard.content,
    F.text | F.photo | F.video | F.document | F.animation,
)
async def wiz_content(message: Message, state: FSMContext) -> None:
    preview = (message.caption or message.text or "").strip()
    if not preview:
        preview = "(Foto)" if message.photo else "(Medien)"
    await state.update_data(
        src_chat=message.chat.id, src_msg=message.message_id, preview=preview[:200]
    )
    await state.set_state(BroadcastWizard.audience)
    await message.answer("👥 <b>An wen?</b>", reply_markup=_audience_keyboard())


@router.callback_query(F.data.startswith("bc:aud:"))
async def cb_audience(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    if "src_msg" not in data:
        await cb.answer("Bitte zuerst /broadcast starten.", show_alert=True)
        return
    audience = BroadcastAudience(cb.data.split(":")[-1])
    count = len(await bc_svc.audience_telegram_ids(session, audience))
    await state.update_data(audience=audience.value)
    await state.set_state(BroadcastWizard.button)
    kb = InlineKeyboardBuilder()
    kb.button(text="⏭ Ohne Button", callback_data="bc:btn:skip")
    await cb.message.edit_text(
        f"👥 Zielgruppe: <b>{bc_svc.audience_label(audience)}</b> ({count} Nutzer)\n\n"
        "🔘 <b>Button?</b> Sende <code>Text | https://link</code> — "
        "oder überspringen.",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.message(BroadcastWizard.button, F.text)
async def wiz_button(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if "|" not in raw:
        await message.answer("⚠️ Format: <code>Button-Text | https://link</code>")
        return
    text, _, url = (part.strip() for part in raw.partition("|"))
    if not text or not url.startswith(("http://", "https://", "tg://")):
        await message.answer("⚠️ Der Link muss mit http(s):// beginnen.")
        return
    await state.update_data(btn_text=text[:64], btn_url=url[:512])
    await state.set_state(BroadcastWizard.when)
    await message.answer("⏰ <b>Wann senden?</b>", reply_markup=_when_keyboard())


@router.callback_query(F.data == "bc:btn:skip")
async def cb_button_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(btn_text=None, btn_url=None)
    await state.set_state(BroadcastWizard.when)
    await cb.message.edit_text("⏰ <b>Wann senden?</b>", reply_markup=_when_keyboard())
    await cb.answer()


@router.callback_query(F.data.startswith("bc:when:"))
async def cb_when(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    choice = cb.data.split(":")[-1]
    if choice == "custom":
        await state.set_state(BroadcastWizard.custom_time)
        await cb.message.edit_text(
            "✍️ Zeitpunkt senden: <code>2h</code>, <code>30m</code>, "
            "<code>18:30</code> oder <code>24.12. 18:00</code>"
        )
        await cb.answer()
        return
    from datetime import datetime, timedelta

    when = {
        "now": None,
        "1h": datetime.now() + timedelta(hours=1),
        "3h": datetime.now() + timedelta(hours=3),
        "tomorrow9": (datetime.now() + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        ),
    }.get(choice)
    await state.update_data(when=when.isoformat() if when else None)
    await _show_preview(cb.message, session, state)
    await cb.answer()


@router.message(BroadcastWizard.custom_time, F.text)
async def wiz_custom_time(message: Message, session: AsyncSession, state: FSMContext) -> None:
    try:
        when = bc_svc.parse_schedule(message.text or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    await state.update_data(when=when.isoformat() if when else None)
    await _show_preview(message, session, state)


async def _show_preview(message: Message, session: AsyncSession, state: FSMContext) -> None:
    from datetime import datetime

    await state.set_state(BroadcastWizard.confirm)
    data = await state.get_data()
    audience = BroadcastAudience(data.get("audience", "all"))
    count = len(await bc_svc.audience_telegram_ids(session, audience))
    markup = _button_markup(data.get("btn_text"), data.get("btn_url"))
    # The preview IS the real thing: Telegram copies the original message.
    await message.bot.copy_message(
        chat_id=message.chat.id, from_chat_id=data["src_chat"],
        message_id=data["src_msg"], reply_markup=markup,
    )
    when = data.get("when")
    when_text = (
        f"⏰ {datetime.fromisoformat(when):%d.%m.%Y %H:%M}" if when else "🚀 sofort"
    )
    await message.answer(
        "👆 <b>Vorschau</b> — genau so kommt es an.\n\n"
        f"👥 Zielgruppe: <b>{bc_svc.audience_label(audience)}</b> ({count} Nutzer)\n"
        f"🕒 Zeitpunkt: <b>{when_text}</b>\n\n"
        "Senden?",
        reply_markup=_confirm_keyboard(),
    )


@router.callback_query(F.data == "bc:confirm")
async def cb_confirm(
    cb: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    from datetime import datetime

    if not has_role(user, UserRole.ADMIN):
        await cb.answer("⛔", show_alert=True)
        return
    data = await state.get_data()
    if "src_msg" not in data:
        await cb.answer("Entwurf verloren — bitte /broadcast neu starten.", show_alert=True)
        return
    await state.clear()
    when = datetime.fromisoformat(data["when"]) if data.get("when") else None
    if when is not None and when.tzinfo is None:
        when = when.astimezone()  # local wall time → aware timestamp

    status = await cb.message.answer(
        f"⏰ Broadcast geplant für {when:%d.%m.%Y %H:%M} — du bekommst hier den Bericht."
        if when else "📢 Broadcast läuft an — Fortschritt erscheint hier…"
    )
    b = await bc_svc.create_broadcast(
        session,
        created_by=user.telegram_id,
        audience=BroadcastAudience(data.get("audience", "all")),
        preview=data.get("preview", ""),
        source_chat_id=data["src_chat"],
        source_message_id=data["src_msg"],
        button_text=data.get("btn_text"),
        button_url=data.get("btn_url"),
        scheduled_at=when,
        status_chat_id=status.chat.id,
        status_message_id=status.message_id,
    )
    logger.info("ADMIN: {} confirmed broadcast #{}", user.telegram_id, b.id)
    await cb.message.edit_text(
        f"✅ Broadcast <b>#{b.id}</b> angelegt. Übersicht: /broadcasts"
    )
    await cb.answer()


@router.message(BroadcastWizard.audience)
@router.message(BroadcastWizard.when)
@router.message(BroadcastWizard.confirm)
async def wiz_use_buttons(message: Message) -> None:
    """Keep stray messages inside the wizard instead of leaking into search."""
    await message.answer("👆 Bitte die Buttons oben nutzen — oder /cancel.")
