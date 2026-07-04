"""/start and /help entrypoints."""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import language_keyboard, main_menu_keyboard
from app.bot.texts import t
from app.database.models import User

router = Router(name="start")


def _is_new_user(user: User) -> bool:
    """True if the account was created within the last two minutes."""
    created = user.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() < 120


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, lang: str, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("start.greeting", lang))
    if _is_new_user(user):
        # First contact: let the user pick their language right away.
        await message.answer(t("settings.language", lang), reply_markup=language_keyboard())
    else:
        await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))


@router.message(Command("help"))
async def cmd_help(message: Message, lang: str) -> None:
    await message.answer(t("help.body", lang))


@router.message(Command("menu"))
async def cmd_menu(message: Message, lang: str, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))
