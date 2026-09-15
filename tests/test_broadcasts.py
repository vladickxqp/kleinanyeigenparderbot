"""Tests for the broadcast engine: scheduling, audiences, delivery counters."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import (
    BroadcastAudience,
    BroadcastStatus,
    SubscriptionTier,
    User,
)
from app.services import broadcasts as bc
from app.services.broadcasts import SendResult, parse_schedule

NOW = datetime(2026, 9, 14, 12, 0)


# --- Scheduling ---------------------------------------------------------------------
def test_parse_schedule_now_and_relative():
    assert parse_schedule("jetzt", now=NOW) is None
    assert parse_schedule("now", now=NOW) is None
    assert parse_schedule("2h", now=NOW) == NOW + timedelta(hours=2)
    assert parse_schedule("30m", now=NOW) == NOW + timedelta(minutes=30)
    assert parse_schedule("1d", now=NOW) == NOW + timedelta(days=1)


def test_parse_schedule_clock_today_or_tomorrow():
    assert parse_schedule("18:30", now=NOW) == NOW.replace(hour=18, minute=30)
    # Already past today -> tomorrow.
    assert parse_schedule("09:00", now=NOW) == (NOW + timedelta(days=1)).replace(hour=9, minute=0)


def test_parse_schedule_date_and_errors():
    assert parse_schedule("24.12. 18:00", now=NOW) == NOW.replace(month=12, day=24, hour=18, minute=0)
    with pytest.raises(ValueError):
        parse_schedule("bald mal", now=NOW)
    with pytest.raises(ValueError):
        parse_schedule("25:99", now=NOW)


# --- DB-backed --------------------------------------------------------------------------
@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


async def _setup_users(session) -> None:
    session.add_all(
        [
            User(telegram_id=1, subscription=SubscriptionTier.FREE),
            User(telegram_id=2, subscription=SubscriptionTier.UNLIMITED),
            User(telegram_id=3, subscription=SubscriptionTier.FREE, is_active=False),
            User(telegram_id=4, subscription=SubscriptionTier.PRO, is_blocked=True),
            User(telegram_id=5, subscription=SubscriptionTier.FREE),
        ]
    )
    await session.flush()


def test_audiences_and_delivery(sqlite_db):
    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[Base.metadata.tables["users"], Base.metadata.tables["broadcasts"]],
            )
        maker = db.get_sessionmaker()
        async with maker() as session:
            await _setup_users(session)

            # Inactive (3) and blocked (4) users are never addressed.
            assert await bc.audience_telegram_ids(session, BroadcastAudience.ALL) == [1, 2, 5]
            assert await bc.audience_telegram_ids(session, BroadcastAudience.FREE) == [1, 5]
            assert await bc.audience_telegram_ids(session, BroadcastAudience.PREMIUM) == [2]

            b = await bc.create_broadcast(
                session, created_by=999, audience=BroadcastAudience.ALL,
                preview="Hallo", text="Hallo",
            )
            assert b.status is BroadcastStatus.SCHEDULED

            outcomes = {1: SendResult.SENT, 2: SendResult.BLOCKED, 5: SendResult.FAILED}
            progress: list[tuple[int, int]] = []

            async def fake_send(tg_id: int) -> SendResult:
                return outcomes[tg_id]

            async def on_progress(done: int, total: int) -> None:
                progress.append((done, total))

            await bc.run_broadcast(
                session, b, fake_send, progress_fn=on_progress, pace_seconds=0
            )
            assert (b.total, b.sent, b.blocked, b.failed) == (3, 1, 1, 1)
            assert b.status is BroadcastStatus.DONE and b.finished_at is not None
            assert progress[-1] == (3, 3)  # final progress tick always fires

            # The blocked recipient was deactivated -> excluded from now on.
            assert await bc.audience_telegram_ids(session, BroadcastAudience.ALL) == [1, 5]
            assert "1/3 ✅" in bc.summary_line(b)
        await db.dispose_engine()

    asyncio.run(scenario())


def test_claim_due_and_cancel(sqlite_db):
    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[Base.metadata.tables["users"], Base.metadata.tables["broadcasts"]],
            )
        maker = db.get_sessionmaker()
        async with maker() as session:
            from datetime import timezone

            now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
            immediate = await bc.create_broadcast(
                session, created_by=1, audience=BroadcastAudience.ALL, preview="a", text="a"
            )
            future = await bc.create_broadcast(
                session, created_by=1, audience=BroadcastAudience.ALL, preview="b", text="b",
                scheduled_at=now + timedelta(hours=2),
            )
            past = await bc.create_broadcast(
                session, created_by=1, audience=BroadcastAudience.ALL, preview="c", text="c",
                scheduled_at=now - timedelta(minutes=1),
            )

            due = await bc.claim_due(session, now=now)
            assert sorted(due) == sorted([immediate.id, past.id])
            assert immediate.status is BroadcastStatus.SENDING
            assert future.status is BroadcastStatus.SCHEDULED

            # Claiming again must not hand out the same broadcasts twice.
            assert await bc.claim_due(session, now=now) == []

            # Only still-scheduled broadcasts can be cancelled.
            assert await bc.cancel_scheduled(session, future.id) is True
            assert await bc.cancel_scheduled(session, immediate.id) is False
            assert future.status is BroadcastStatus.CANCELED

            with pytest.raises(ValueError):
                await bc.create_broadcast(
                    session, created_by=1, audience=BroadcastAudience.ALL, preview="x"
                )
        await db.dispose_engine()

    asyncio.run(scenario())
