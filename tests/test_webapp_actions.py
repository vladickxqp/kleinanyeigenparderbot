"""The Mini App gets the two switches the chat card always had, and a speed limit.

Star and hide were bot-only: the app could FILTER favourites but not make one.
And the API had no rate limit — a valid initData was a licence to hammer it.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from app.api import webapp_auth
from app.api.routers import webapp as api
from app.config.settings import settings
from app.database import session as db
from app.database.base import Base
from app.database.models import Listing, SearchRule, SiteName, User

TOKEN = "123456:TEST-TOKEN"


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


async def _tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _owner_with_listing(session, tg: int):
    user = User(telegram_id=tg)
    session.add(user)
    await session.flush()
    rule = SearchRule(user_id=user.id, name="phones", keywords="iphone")
    session.add(rule)
    await session.flush()
    row = Listing(
        rule_id=rule.id, site=SiteName.KLEINANZEIGEN, external_id=f"e{tg}",
        fingerprint=f"fp{tg}", title="iPhone 14", url="https://example.com/x",
        price=500.0, notified=True,
    )
    session.add(row)
    await session.flush()
    return user, row


# --- Star and hide --------------------------------------------------------------------
def test_the_star_is_a_switch(sqlite_db):
    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user, row = await _owner_with_listing(session, 11)
            await session.commit()
            on = await api.toggle_favorite(row.id, user=user, session=session)
            off = await api.toggle_favorite(row.id, user=user, session=session)
            favourites = await api.listings(user=user, session=session, limit=30, favorites=True)
        await db.dispose_engine()
        return on.is_favorite, off.is_favorite, favourites

    on, off, favourites = asyncio.run(scenario())
    assert on is True and off is False
    assert favourites == []


def test_hidden_means_gone_from_the_list(sqlite_db):
    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user, row = await _owner_with_listing(session, 12)
            await session.commit()
            before = await api.listings(user=user, session=session, limit=30, favorites=False)
            response = await api.ignore_listing(row.id, user=user, session=session)
            after = await api.listings(user=user, session=session, limit=30, favorites=False)
        await db.dispose_engine()
        return len(before), response.status_code, len(after)

    assert asyncio.run(scenario()) == (1, 204, 0)


def test_somebody_else_s_find_cannot_be_touched(sqlite_db):
    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            _, row = await _owner_with_listing(session, 13)
            intruder = User(telegram_id=14)
            session.add(intruder)
            await session.flush()
            await session.commit()
            codes = []
            for call in (api.toggle_favorite, api.ignore_listing):
                try:
                    await call(row.id, user=intruder, session=session)
                except HTTPException as exc:
                    codes.append(exc.status_code)
            await session.refresh(row)
            untouched = (row.is_favorite, row.is_ignored)
        await db.dispose_engine()
        return codes, untouched

    codes, untouched = asyncio.run(scenario())
    assert codes == [404, 404]
    assert untouched == (False, False)


# --- The speed limit ------------------------------------------------------------------
def _init_data(tg: int = 5933423757) -> str:
    fields = {
        "auth_date": str(int(time.time()) - 60),
        "query_id": "AAH",
        "user": json.dumps({"id": tg, "first_name": "Vlad"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def _login(monkeypatch, *, limited: bool):
    seen: list[tuple[str, int, int]] = []

    async def gate(key, limit, window):  # noqa: ANN001
        seen.append((key, limit, window))
        return limited

    monkeypatch.setattr(settings, "bot_token", TOKEN)
    monkeypatch.setattr(webapp_auth.throttle, "rate_limited", gate)

    async def scenario():
        await _tables()
        async with db.get_sessionmaker()() as session:
            try:
                user = await webapp_auth.current_webapp_user(_init_data(), session=session)
                outcome = ("ok", user.id)
            except HTTPException as exc:
                outcome = ("http", exc.status_code)
        await db.dispose_engine()
        return outcome

    return asyncio.run(scenario()), seen


def test_a_user_over_the_limit_gets_429_not_service(sqlite_db, monkeypatch):
    outcome, seen = _login(monkeypatch, limited=True)
    assert outcome == ("http", 429)
    assert len(seen) == 1


def test_the_limit_is_per_user_and_the_normal_case_passes(sqlite_db, monkeypatch):
    outcome, seen = _login(monkeypatch, limited=False)
    assert outcome[0] == "ok"
    key, limit, window = seen[0]
    assert key == f"webapp:{outcome[1]}"
    assert limit == webapp_auth.WEBAPP_REQUESTS_PER_WINDOW
    assert window == webapp_auth.WEBAPP_WINDOW_SECONDS
