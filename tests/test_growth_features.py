"""Weekly recap, business metrics and the purchasable plan ladder."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import (
    Flip,
    FlipStatus,
    Listing,
    Payment,
    SearchRule,
    SiteName,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)
from app.services.analytics import business_metrics, format_metrics
from app.services.recap import build_recap, format_recap

TABLES = [
    "users", "search_rules", "listings", "flips",
    "subscriptions", "payments",
]


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


async def _create_tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Base.metadata.tables[name] for name in TABLES],
        )


def test_weekly_recap_adds_up_savings_and_profit(sqlite_db):
    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=42)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="r", keywords="ps5")
            session.add(rule)
            await session.flush()

            for i, (price, market, discount) in enumerate(
                [(300.0, 400.0, 25.0), (250.0, 300.0, 16.0), (100.0, 110.0, 9.0)]
            ):
                session.add(
                    Listing(
                        rule_id=rule.id, site=SiteName.KLEINANZEIGEN,
                        external_id=f"e{i}", fingerprint=f"f{i}",
                        title=f"PS5 Nr {i}", url=f"https://x.test/{i}",
                        price=price, estimated_market_price=market,
                        discount_percent=discount, notified=True,
                    )
                )
            session.add(
                Flip(
                    telegram_id=user.telegram_id, title="PS5", buy_price=200.0,
                    sell_price=300.0, net_profit=55.0, status=FlipStatus.SOLD,
                    sold_at=datetime.now(timezone.utc) - timedelta(days=2),
                )
            )
            await session.flush()

            recap = await build_recap(session, user)
            assert recap.finds == 3
            assert recap.potential_savings == 160.0   # 100 + 50 + 10
            assert recap.best_title == "PS5 Nr 0"     # highest discount first
            assert recap.flips_sold == 1
            assert recap.flip_profit == 55.0
            assert recap.worth_sending is True

            text = format_recap(recap, referral_link="https://t.me/bot?start=ref_42")
            assert "160 €" in text
            assert "PS5 Nr 0" in text
            assert "ref_42" in text
        await db.dispose_engine()

    asyncio.run(scenario())


def test_recap_is_skipped_when_there_is_nothing_to_report(sqlite_db):
    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=43)
            session.add(user)
            await session.flush()
            recap = await build_recap(session, user)
            assert recap.finds == 0
            assert recap.worth_sending is False
        await db.dispose_engine()

    asyncio.run(scenario())


def test_business_metrics_report_revenue_churn_and_conversion(sqlite_db):
    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            now = datetime.now(timezone.utc)
            user = User(telegram_id=1, subscription=SubscriptionTier.UNLIMITED)
            churned_user = User(telegram_id=2)
            session.add_all([user, churned_user])
            await session.flush()

            session.add_all([
                Subscription(
                    user_id=user.id, telegram_id=1,
                    status=SubscriptionStatus.ACTIVE,
                    subscription_start=now - timedelta(days=5),
                    subscription_end=now + timedelta(days=25),
                ),
                Subscription(
                    user_id=churned_user.id, telegram_id=2,
                    status=SubscriptionStatus.EXPIRED,
                    subscription_start=now - timedelta(days=40),
                    subscription_end=now - timedelta(days=3),
                ),
            ])
            session.add_all([
                Payment(telegram_id=1, provider="telegram_stars", status="paid",
                        amount_stars=250, amount_eur=4.99,
                        created_at=now - timedelta(days=2)),
                Payment(telegram_id=2, provider="trial", status="granted",
                        created_at=now - timedelta(days=40)),
                Payment(telegram_id=2, provider="telegram_stars", status="paid",
                        amount_stars=250, amount_eur=4.99,
                        created_at=now - timedelta(days=39)),
            ])
            await session.flush()

            m = await business_metrics(session, now=now)
            assert m.active_subs == 1
            assert m.new_subs == 1
            assert m.churned == 1
            assert m.churn_percent == 50.0
            assert m.revenue_30d == 4.99
            assert m.revenue_prev_30d == 4.99
            assert m.trials_started == 1
            assert m.trials_converted == 1
            assert m.trial_conversion_percent == 100.0

            block = format_metrics(m)
            assert "Churn" in block and "4.99" in block
        await db.dispose_engine()

    asyncio.run(scenario())


def test_plan_ladder_maps_payloads_to_tiers():
    from app.services.premium import available_plans, plan_by_key, plan_for_payload

    plans = available_plans()
    assert [p.key for p in plans] == ["pro", "unlimited"]
    assert plans[0].price_stars < plans[1].price_stars
    assert plan_by_key("pro").tier is SubscriptionTier.PRO
    assert plan_by_key("nonsense").tier is SubscriptionTier.UNLIMITED

    assert plan_for_payload("premium_monthly:pro").key == "pro"
    assert plan_for_payload("premium_monthly:pro:CODE").key == "pro"
    # Legacy links put the coupon straight after the prefix.
    assert plan_for_payload("premium_monthly:SOMMER").key == "unlimited"
    assert plan_for_payload("premium_monthly").key == "unlimited"


def test_stars_are_converted_to_the_amount_actually_charged():
    from app.services.premium import stars_to_eur
    from app.config.settings import settings

    assert stars_to_eur(settings.premium_price_stars) == pytest.approx(
        settings.premium_price_eur, abs=0.01
    )
    # A coupon purchase must not be booked as a full-price sale.
    assert stars_to_eur(1) < settings.premium_price_eur
    assert stars_to_eur(0) == 0.0
