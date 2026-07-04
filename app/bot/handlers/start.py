"""/start and /help entrypoints."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import main_menu_keyboard
from app.bot.texts import t
from app.database.models import User

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, lang: str, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("start.greeting", lang))
    await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))


@router.message(Command("help"))
async def cmd_help(message: Message, lang: str) -> None:
    await message.answer(t("help.body", lang))


@router.message(Command("menu"))
async def cmd_menu(message: Message, lang: str, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))
