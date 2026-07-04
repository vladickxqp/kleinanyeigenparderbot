"""Middleware that opens a DB session and resolves the current user per update.

Injects ``session`` (AsyncSession) and ``user`` (ORM User) into every handler's
kwargs, and short-circuits blocked users. Commits at the end of the handler.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from loguru import logger

from app.database.session import get_sessionmaker
from app.services.repositories import UserRepository


class UserContextMiddleware(BaseMiddleware):
    """Provide ``session`` and ``user`` to handlers; upsert the Telegram user."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        maker = get_sessionmaker()
        async with maker() as session:
            repo = UserRepository(session)
            user = await repo.get_or_create(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
                language_code=tg_user.language_code,
            )
            if user.is_blocked:
                logger.info("Blocked user {} ignored", tg_user.id)
                await session.commit()
                return None

            data["session"] = session
            data["user"] = user
            data["lang"] = user.language_code
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
