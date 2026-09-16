"""Built-in support chat: users write to the admins, admins reply — all inside
the bot, no external software.

Flow:
  1. User: /support (or the 💬 button) → FSM asks for the message.
  2. The message is forwarded to every admin/moderator+ with a ready-to-copy
     ``/reply <telegram_id> …`` command attached.
  3. Admin: ``/reply <telegram_id> <text>`` → the user receives the answer,
     marked as coming from support.

The conversation link is the user's telegram id — stateless and robust.
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import DEFAULT_LANGUAGE, t
from app.config.settings import settings
from app.database.models import User, UserRole
from app.services.roles import effective_role, has_role

router = Router(name="support")

#: Cap forwarded support messages (Telegram message limit is 4096 anyway).
MAX_SUPPORT_LENGTH = 1500


class SupportState(StatesGroup):
    waiting_message = State()


async def _support_staff_ids(session: AsyncSession) -> list[int]:
    """Telegram ids of everyone who should receive support requests."""
    result = await session.execute(select(User))
    staff = [
        u.telegram_id
        for u in result.scalars().all()
        if has_role(u, UserRole.MODERATOR)
    ]
    # Env-bootstrapped owners might not have a DB row yet.
    for admin_id in settings.admin_ids:
        if admin_id not in staff:
            staff.append(admin_id)
    return staff


# --- User side -------------------------------------------------------------------
@router.message(Command("support"))
async def cmd_support(message: Message, lang: str, state: FSMContext) -> None:
    await state.set_state(SupportState.waiting_message)
    await message.answer(t("support.prompt", lang))


@router.callback_query(F.data == "menu:support")
async def cb_support(cb: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.set_state(SupportState.waiting_message)
    await cb.message.answer(t("support.prompt", lang))
    await cb.answer()


@router.message(SupportState.waiting_message, Command("cancel"))
async def cmd_support_cancel(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer("✖️ " + t("common.cancelled", lang))


@router.message(SupportState.waiting_message, F.text)
async def support_message(
    message: Message, user: User, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    await state.clear()
    text = (message.text or "").strip()[:MAX_SUPPORT_LENGTH]
    if not text:
        await message.answer(t("support.empty", lang))
        return

    staff = await _support_staff_ids(session)
    # Normally staff do not need their own ticket back — but when the sender
    # IS the only staff member (solo owner testing the flow), skipping them
    # would deliver the ticket to nobody while still claiming success.
    recipients = [s for s in staff if s != user.telegram_id] or staff

    # Staff-facing, like the whole admin area: always German.
    ticket = (
        "💬 <b>Support-Anfrage</b>\n"
        f"Von: <b>{escape(user.display_name)}</b> "
        f"(<code>{user.telegram_id}</code>, {user.subscription.value})\n\n"
        f"{escape(text)}\n\n"
        f"Antworten: <code>/reply {user.telegram_id} </code>"
    )
    delivered = 0
    for staff_id in recipients:
        try:
            await message.bot.send_message(staff_id, ticket)
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Support ticket to {} failed: {}", staff_id, exc)

    logger.info(
        "SUPPORT: request from {} delivered to {}/{} staff member(s)",
        user.telegram_id, delivered, len(recipients),
    )
    if delivered:
        await message.answer(t("support.delivered", lang))
    else:
        # Never claim success when nothing was delivered.
        await message.answer(t("support.undelivered", lang))


# --- Admin side ------------------------------------------------------------------
@router.message(Command("reply"))
async def cmd_reply(
    message: Message, user: User, session: AsyncSession, command: CommandObject
) -> None:
    if not has_role(user, UserRole.MODERATOR):
        return

    args = (command.args or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Nutzung: <code>/reply &lt;telegram_id&gt; &lt;Antwort&gt;</code>"
        )
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await message.answer("⚠️ Die Telegram-ID muss eine Zahl sein.")
        return
    answer_text = args[1].strip()[:MAX_SUPPORT_LENGTH]

    # The answer is read by the user, not by the staff member typing it, so it
    # goes out in the recipient's language.
    target_lang = (
        await session.scalar(
            select(User.language_code).where(User.telegram_id == target_id)
        )
        or DEFAULT_LANGUAGE
    )

    try:
        await message.bot.send_message(
            target_id, t("support.answer", target_lang, text=escape(answer_text))
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(
            f"⚠️ Konnte nicht zustellen (<code>{escape(str(exc)[:150])}</code>) — "
            "hat die Person den Bot blockiert?"
        )
        return

    logger.info(
        "SUPPORT: {} ({}) replied to {}",
        user.telegram_id, effective_role(user).value, target_id,
    )
    await message.answer(f"✅ Antwort an <code>{target_id}</code> zugestellt.")
