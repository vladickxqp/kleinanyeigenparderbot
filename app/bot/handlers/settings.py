"""Settings: language selection."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import language_keyboard, main_menu_keyboard
from app.bot.texts import SUPPORTED_LANGUAGES, t
from app.database.models import User

router = Router(name="settings")


@router.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery, lang: str) -> None:
    await cb.message.edit_text(
        t("settings.language", lang), reply_markup=language_keyboard()
    )
    await cb.answer()


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
