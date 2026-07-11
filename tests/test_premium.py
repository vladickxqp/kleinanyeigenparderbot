"""Tests for the premium subscription lifecycle (SQLite in-memory)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import (
    PlanType,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)
from app.services.premium import (
    activate_premium,
    deactivate_premium,
    expire_overdue_subscriptions,
    get_active_subscription,
)


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


async def _setup() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        # Only the tables premium needs — SearchRule uses postgres ARRAY.
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Base.metadata.tables["users"],
                Base.metadata.tables["subscriptions"],
            ],
        )


def test_activate_extend_and_expire(sqlite_db):
    async def scenario() -> None:
        await _setup()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=111, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            # First purchase: user becomes premium with an active subscription.
            sub = await activate_premium(
                session, user, days=31, charge_id="ch_1", price_stars=250
            )
            assert user.subscription is SubscriptionTier.UNLIMITED
            assert sub.status is SubscriptionStatus.ACTIVE
            first_end = sub.subscription_end

            # Renewal charge: the SAME subscription is extended by 31 days.
            sub2 = await activate_premium(
                session, user, days=31, charge_id="ch_2", price_stars=250
            )
            assert sub2.id == sub.id
            assert sub2.subscription_end > first_end
            assert sub2.payments_count == 2

            # Force the end date into the past -> nightly sweep downgrades.
            sub2.subscription_end = datetime.now(timezone.utc) - timedelta(days=1)
            await session.flush()
            downgraded = await expire_overdue_subscriptions(session)
            assert downgraded == [111]
            assert user.subscription is SubscriptionTier.FREE
            assert sub2.status is SubscriptionStatus.EXPIRED
            assert await get_active_subscription(session, 111) is None
        await db.dispose_engine()

    asyncio.run(scenario())


def test_admin_grant_and_revoke(sqlite_db):
    async def scenario() -> None:
        await _setup()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=222, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            sub = await activate_premium(
                session, user, days=7, provider="admin_grant",
                plan=PlanType.ADMIN_GRANT,
            )
            assert user.subscription is SubscriptionTier.UNLIMITED
            assert sub.plan_type is PlanType.ADMIN_GRANT
            assert sub.payment_status == "granted"

            await deactivate_premium(session, user)
            assert user.subscription is SubscriptionTier.FREE
            assert await get_active_subscription(session, 222) is None
        await db.dispose_engine()

    asyncio.run(scenario())


def test_tier_limits_come_from_settings(monkeypatch):
    from app.config.settings import settings as app_settings

    monkeypatch.setattr(app_settings, "free_max_rules", 5)
    monkeypatch.setattr(app_settings, "free_min_interval_seconds", 900)
    user = User(telegram_id=1, subscription=SubscriptionTier.FREE)
    assert user.max_rules == 5
    assert user.min_interval_seconds == 900
    assert user.is_paid_tier is False

    paid = User(telegram_id=2, subscription=SubscriptionTier.UNLIMITED)
    assert paid.is_paid_tier is True
