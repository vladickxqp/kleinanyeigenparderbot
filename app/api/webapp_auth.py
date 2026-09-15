"""Telegram Mini App authentication.

A Mini App gets ``window.Telegram.WebApp.initData`` — a query string signed by
Telegram with a key derived from the bot token. The frontend sends it in the
``X-Telegram-Init-Data`` header; we verify the HMAC, reject stale data and
resolve (or create) the bot user. No passwords, no JWT: Telegram IS the login.

Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import User
from app.database.session import get_session
from app.services.repositories import UserRepository

#: initData older than this is refused (replay protection).
#: Telegram re-issues initData whenever the Mini App opens, so a short window
#: is enough — and it keeps a captured string from being replayable all day.
MAX_AGE_SECONDS = 15 * 60


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age: int = MAX_AGE_SECONDS,
    now: float | None = None,
) -> dict:
    """Verify Telegram's signature; return the parsed fields (``user`` as dict).

    Raises ``ValueError`` with a short reason on any problem.
    """
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("hash missing")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise ValueError("bad signature")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise ValueError("bad auth_date") from exc
    if (now if now is not None else time.time()) - auth_date > max_age:
        raise ValueError("expired")

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError("bad user") from exc
    if not isinstance(user, dict) or "id" not in user:
        raise ValueError("user missing")
    pairs["user"] = user
    return pairs


async def current_webapp_user(
    x_telegram_init_data: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: the authenticated Mini App user (created on first visit)."""
    if not x_telegram_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bitte in Telegram öffnen (initData fehlt).",
        )
    try:
        data = validate_init_data(x_telegram_init_data, settings.bot_token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"initData ungültig: {exc}"
        ) from exc

    tg = data["user"]
    user = await UserRepository(session).get_or_create(
        telegram_id=int(tg["id"]),
        username=tg.get("username"),
        first_name=tg.get("first_name"),
        last_name=tg.get("last_name"),
        language_code=tg.get("language_code"),
    )
    await session.commit()
    if user.is_blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gesperrt.")
    return user
