"""Settings: language selection and quiet hours."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import language_keyboard, main_menu_keyboard
from app.bot.texts import SUPPORTED_LANGUAGES, t
from app.database.models import User
from app.services import quiet

router = Router(name="settings")

#: Offered quiet-hour presets as (start_hour, end_hour).
QUIET_PRESETS: list[tuple[int, int]] = [(22, 7), (23, 8), (0, 9)]


def _settings_menu(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Sprache / Language", callback_data="settings:lang")
    kb.button(text="🌙 Ruhezeiten", callback_data="settings:quiet")
    kb.row(InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:home"))
    kb.adjust(1)
    return kb.as_markup()


def _quiet_keyboard(lang: str):
    kb = InlineKeyboardBuilder()
    for start, end in QUIET_PRESETS:
        kb.button(
            text=f"🌙 {start:02d}:00 – {end:02d}:00",
            callback_data=f"quiet:{start}:{end}",
        )
    kb.button(text="🔔 Aus (immer benachrichtigen)", callback_data="quiet:off")
    kb.row(
        InlineKeyboardButton(text=t("btn.back", lang), callback_data="menu:settings")
    )
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery, lang: str) -> None:
    await cb.message.edit_text(
        "⚙️ <b>Einstellungen</b>", reply_markup=_settings_menu(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "settings:lang")
async def cb_settings_lang(cb: CallbackQuery, lang: str) -> None:
    await cb.message.edit_text(
        t("settings.language", lang), reply_markup=language_keyboard()
    )
    await cb.answer()


async def _render_quiet(cb: CallbackQuery, user: User, lang: str) -> None:
    from aiogram.exceptions import TelegramBadRequest

    window = await quiet.get_quiet(user.telegram_id)
    current = (
        f"🌙 Aktiv: <b>{window[0]:02d}:00 – {window[1]:02d}:00</b>"
        if window
        else "🔔 Aus — du wirst immer sofort benachrichtigt."
    )
    try:
        await cb.message.edit_text(
            "🌙 <b>Ruhezeiten</b>\n\n"
            f"{current}\n\n"
            "In diesem Fenster sammelt der Bot neue Angebote und schickt sie dir "
            "danach gesammelt als ☀️ Morgen-Digest.",
            reply_markup=_quiet_keyboard(lang),
        )
    except TelegramBadRequest:
        pass  # unchanged content (same preset tapped twice) is fine


@router.callback_query(F.data == "settings:quiet")
async def cb_settings_quiet(cb: CallbackQuery, user: User, lang: str) -> None:
    await _render_quiet(cb, user, lang)
    await cb.answer()


@router.callback_query(F.data.startswith("quiet:"))
async def cb_set_quiet(cb: CallbackQuery, user: User, lang: str) -> None:
    parts = cb.data.split(":")
    if parts[1] == "off":
        await quiet.set_quiet(user.telegram_id, None, None)
        await cb.answer("🔔 Ruhezeiten aus")
    else:
        try:
            start, end = int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            await cb.answer()
            return
        if not (0 <= start <= 23 and 0 <= end <= 23):
            await cb.answer()
            return
        await quiet.set_quiet(user.telegram_id, start, end)
        await cb.answer(f"🌙 Ruhe von {start:02d}:00 bis {end:02d}:00")
    await _render_quiet(cb, user, lang)


@router.callback_query(F.data.startswith("lang:"))
async def cb_set_language(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    new_lang = cb.data.split(":")[-1]
    if new_lang not in SUPPORTED_LANGUAGES:
        await cb.answer("Unsupported", show_alert=True)
        return
    user.language_code = new_lang
    await session.flush()
    await cb.message.edit_text(
        t("settings.language_set", new_lang), reply_markup=main_menu_keyboard(new_lang)
    )
    await cb.answer()
