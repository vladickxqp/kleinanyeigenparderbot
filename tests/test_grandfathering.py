"""Existing subscribers must never lose what they bought.

Telegram cannot reprice a running Stars subscription: an old subscriber keeps
paying the old amount forever, and their renewal arrives carrying an invoice
payload issued before the current plans existed. Nothing in that flow may read
"paid less than the cheapest plan costs today" as "give them the cheapest
plan".
"""

from __future__ import annotations

import asyncio
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
from app.services.premium import activate_premium, plan_for_payload

TABLES = ["users", "subscriptions", "search_rules", "payments"]


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
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Base.metadata.tables[name] for name in TABLES],
        )


def test_a_renewal_never_downgrades_an_existing_subscriber(sqlite_db):
    """The classic way to lose a customer: charge them, then take rights away."""

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=11, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            # Bought the old flagship plan back when it cost 250 stars.
            first = await activate_premium(
                session, user, days=31, charge_id="ch_old_1", price_stars=250,
                tier=SubscriptionTier.UNLIMITED,
            )
            assert user.subscription is SubscriptionTier.UNLIMITED
            assert first.tier == "unlimited"

            # A month later Telegram charges the SAME old amount again. Today
            # 250 stars would only buy the cheapest plan.
            renewal_plan = plan_for_payload("premium_monthly")
            assert renewal_plan.key == "starter"       # a bare payload is cheapest
            second = await activate_premium(
                session, user, days=31, charge_id="ch_old_2", price_stars=250,
                tier=renewal_plan.tier,
            )
            assert second.id == first.id
            assert user.subscription is SubscriptionTier.UNLIMITED, "renewal downgraded a payer"
            assert second.tier == "unlimited"
        await db.dispose_engine()

    asyncio.run(scenario())


def test_an_upgrade_purchase_still_raises_the_level(sqlite_db):
    """Protecting the old level must not block a deliberate upgrade."""

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=12, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            await activate_premium(
                session, user, days=31, charge_id="ch_s", price_stars=350,
                tier=SubscriptionTier.STARTER,
            )
            assert user.subscription is SubscriptionTier.STARTER

            sub = await activate_premium(
                session, user, days=31, charge_id="ch_p", price_stars=750,
                tier=SubscriptionTier.PRO,
            )
            assert user.subscription is SubscriptionTier.PRO
            assert sub.tier == "pro"
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_grant_never_takes_a_higher_paid_level_away(sqlite_db):
    """A support gift must not silently demote someone who pays for more."""

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=13, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            await activate_premium(
                session, user, days=31, charge_id="ch_u", price_stars=1500,
                tier=SubscriptionTier.UNLIMITED,
            )
            await activate_premium(
                session, user, days=7, provider="admin_grant",
                plan=PlanType.ADMIN_GRANT, tier=SubscriptionTier.STARTER,
            )
            assert user.subscription is SubscriptionTier.UNLIMITED
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_subscription_row_from_before_the_ladder_keeps_its_rights(sqlite_db):
    """Rows written before the tier column existed default to the old flagship."""

    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            from app.database.models import Subscription
            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            user = User(telegram_id=14, subscription=SubscriptionTier.UNLIMITED)
            session.add(user)
            await session.flush()
            # The migration backfills "unlimited" for every pre-existing row.
            session.add(
                Subscription(
                    user_id=user.id, telegram_id=user.telegram_id,
                    status=SubscriptionStatus.ACTIVE, plan_type=PlanType.MONTHLY,
                    subscription_start=now - timedelta(days=20),
                    subscription_end=now + timedelta(days=11),
                    payment_provider="telegram_stars", payment_status="paid",
                    telegram_charge_id="ch_ancient", tier="unlimited",
                    price_stars=250, payments_count=3,
                )
            )
            await session.flush()

            # The next automatic charge carries no plan in its payload at all.
            sub = await activate_premium(
                session, user, days=31, charge_id="ch_ancient_2", price_stars=250,
                tier=plan_for_payload("premium_monthly").tier,
            )
            assert user.subscription is SubscriptionTier.UNLIMITED
            assert sub.tier == "unlimited"
        await db.dispose_engine()

    asyncio.run(scenario())
