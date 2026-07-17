"""Tests for the support system's staff resolution."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.bot.handlers import support as support_mod
from app.database import session as db
from app.database.base import Base
from app.database.models import SubscriptionTier, User, UserRole
from app.services import roles


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(
        db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://")
    )
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


def test_support_staff_resolution(sqlite_db, monkeypatch):
    # Env bootstrap: 999 is owner via BOT_ADMIN_IDS but has no DB row.
    monkeypatch.setattr(roles, "settings", SimpleNamespace(admin_ids=[999]))
    monkeypatch.setattr(support_mod, "settings", SimpleNamespace(admin_ids=[999]))

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all, tables=[Base.metadata.tables["users"]]
            )
        maker = db.get_sessionmaker()
        async with maker() as session:
            session.add_all(
                [
                    User(telegram_id=1, role=UserRole.ADMIN,
                         subscription=SubscriptionTier.FREE),
                    User(telegram_id=2, role=UserRole.MODERATOR,
                         subscription=SubscriptionTier.FREE),
                    User(telegram_id=3, role=UserRole.USER,
                         subscription=SubscriptionTier.FREE),
                ]
            )
            await session.flush()

            staff = await support_mod._support_staff_ids(session)
            # Admin + moderator + env-owner; plain users are NOT staff.
            assert set(staff) == {1, 2, 999}
        await db.dispose_engine()

    asyncio.run(scenario())
