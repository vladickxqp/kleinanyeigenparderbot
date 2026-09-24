"""Settings screen for forwarding deal cards into a channel or group.

The screen is shown to everyone — it is also where a Profi learns what the
Händler level adds — but only a user whose level includes the feature can
set a target. The check is made again on every tap; the keyboard is only
what the user sees, never what they are allowed.
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.reports import locked_text
from app.bot.states import ForwardSetup
from app.bot.texts import t
from app.database.models import User
from app.services import forwarding

router = Router(name="forwarding")


def _keyboard(user: User, lang: str, *, locked: bool):
    kb = InlineKeyboardBuilder()
    if not locked:
        kb.button(text=t("btn.forward_set", lang), callback_data="forward:set")
        if user.forward_chat_id:
            kb.button(text=t("btn.forward_off", lang), callback_data="forward:off")
    kb.row(InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:settings"))
    kb.adjust(1)
    return kb.as_markup()


async def _target_label(cb: CallbackQuery, chat_id: int) -> str:
    """The channel's name for the screen; its id when Telegram will not say."""
    try:
        chat = await cb.bot.get_chat(chat_id)
    except Exception:  # noqa: BLE001 - the screen must render regardless
        return str(chat_id)
    return chat.title or (f"@{chat.username}" if chat.username else str(chat_id))


async def _render(cb: CallbackQuery, user: User, lang: str) -> None:
    locked = not user.has_feature(forwarding.FEATURE)
    lines = [t("forward.title", lang), ""]
    if locked:
        lines.append(locked_text(forwarding.FEATURE, lang))
    elif user.forward_chat_id:
        label = await _target_label(cb, int(user.forward_chat_id))
        lines.append(t("forward.active", lang, target=escape(label)))
    else:
        lines.append(t("forward.inactive", lang))
    lines += ["", t("forward.howto", lang)]
    await cb.message.edit_text(
        "\n".join(lines), reply_markup=_keyboard(user, lang, locked=locked)
    )


@router.callback_query(F.data == "settings:forward")
async def cb_forward(
    cb: CallbackQuery, user: User, lang: str, state: FSMContext
) -> None:
    await state.clear()
    await _render(cb, user, lang)
    await cb.answer()


@router.callback_query(F.data == "forward:set")
async def cb_forward_set(
    cb: CallbackQuery, user: User, lang: str, state: FSMContext
) -> None:
    if not user.has_feature(forwarding.FEATURE):
        await cb.answer(locked_text(forwarding.FEATURE, lang), show_alert=True)
        return
    await state.set_state(ForwardSetup.target)
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.back", lang), callback_data="settings:forward")
    await cb.message.edit_text(t("forward.ask", lang), reply_markup=kb.as_markup())
    await cb.answer()


@router.message(ForwardSetup.target)
async def msg_forward_target(
    message: Message, user: User, session: AsyncSession, lang: str, state: FSMContext
) -> None:
    if not user.has_feature(forwarding.FEATURE):
        await state.clear()
        await message.answer(locked_text(forwarding.FEATURE, lang))
        return
    target = forwarding.parse_target(message)
    if target is None:
        await message.answer(t("forward.not_found", lang))
        return
    check = await forwarding.verify(message.bot, target)
    if not check.ok:
        # The state stays: fix the rights, try again, no need to start over.
        await message.answer(t(f"forward.{check.reason}", lang))
        return
    user.forward_chat_id = check.chat_id
    await session.flush()
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.back", lang), callback_data="menu:settings")
    await message.answer(
        t("forward.ok", lang, target=escape(check.title)), reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "forward:off")
async def cb_forward_off(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    user.forward_chat_id = None
    await session.flush()
    await cb.answer(t("forward.off", lang))
    await _render(cb, user, lang)
