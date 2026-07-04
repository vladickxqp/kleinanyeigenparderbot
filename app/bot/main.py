"""Bot bootstrap: build the Bot/Dispatcher and run polling or webhook."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from loguru import logger

from app.bot.handlers import build_router
from app.bot.middlewares import UserContextMiddleware
from app.config.logging import setup_logging
from app.config.settings import settings


def create_bot() -> Bot:
    if not settings.bot_token or "CHANGE_ME" in settings.bot_token:
        raise RuntimeError(
            "BOT_TOKEN is not configured. Put a fresh @BotFather token in .env."
        )
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    # FSM state survives restarts by living in Redis.
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    middleware = UserContextMiddleware()
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)

    dp.include_router(build_router())
    return dp


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Start / Hauptmenü"),
            BotCommand(command="menu", description="Hauptmenü öffnen"),
            BotCommand(command="help", description="Hilfe"),
        ]
    )


async def run_polling() -> None:
    setup_logging()
    bot = create_bot()
    dp = create_dispatcher()
    await _set_commands(bot)
    me = await bot.get_me()
    logger.info("🤖 Bot @{} started (long polling)", me.username)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


def main() -> None:
    try:
        asyncio.run(run_polling())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")


if __name__ == "__main__":
    main()
