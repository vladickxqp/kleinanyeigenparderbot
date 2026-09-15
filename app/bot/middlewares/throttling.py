"""Per-user flood protection for bot updates.

One person hammering commands costs real money and, worse, real reputation:
every search hits the marketplaces from the same home IP. This middleware caps
how many updates a single Telegram user may trigger per minute, warns once and
then silently drops the rest until the window rolls over.

Admins are exempt, and any Redis problem lets traffic through rather than
silencing the bot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from loguru import logger

from app.config.settings import settings
from app.services.throttle import cooldown, rate_limited

#: Updates allowed per user per window.
LIMIT = 25
WINDOW = 60
#: How often the user is told about it (seconds), to avoid a warning storm.
WARN_EVERY = 60


class ThrottlingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id in settings.admin_ids:
            return await handler(event, data)

        if not await rate_limited(f"upd:{user.id}", limit=LIMIT, window=WINDOW):
            return await handler(event, data)

        logger.info("THROTTLE: dropping update from {}", user.id)
        if not await cooldown(f"warn:{user.id}", WARN_EVERY):
            text = (
                "🐢 Etwas langsamer bitte — du hast gerade sehr viele Aktionen "
                "ausgelöst. In einer Minute geht es normal weiter."
            )
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(text)
            except Exception:  # noqa: BLE001 - never fail on a warning
                pass
        return None
