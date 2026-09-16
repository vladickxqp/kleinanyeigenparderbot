"""The tier ladder, fast slots and usage quotas."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.config.settings import settings
from app.database import session as db
from app.database.base import Base
from app.database.models import SearchRule, SubscriptionTier, User
from app.services import entitlements as ent
from app.services import quota
from app.services.premium import enforce_tier_limits


# --- Entitlements ----------------------------------------------------------------------
def test_every_level_resolves_and_is_ordered():
    tiers = ent.all_tiers()
    assert [e.tier for e in tiers] == [
        SubscriptionTier.FREE, SubscriptionTier.STARTER,
        SubscriptionTier.PRO, SubscriptionTier.UNLIMITED,
    ]
    # Each paid level must differ from the one below on at least two axes.
    for lower, upper in zip(tiers, tiers[1:]):
        axes = 0
        axes += upper.max_rules > lower.max_rules
        axes += upper.fast_slots > lower.fast_slots
        axes += upper.min_interval_seconds < lower.min_interval_seconds
        axes += upper.base_interval_seconds < lower.base_interval_seconds
        axes += (ent.is_unlimited(upper.daily_notifications) and not ent.is_unlimited(lower.daily_notifications)) or (
            not ent.is_unlimited(upper.daily_notifications) and upper.daily_notifications > lower.daily_notifications
        )
        assert axes >= 2, f"{lower.label} -> {upper.label} differs on only {axes} axis"


def test_no_level_undercuts_the_hard_scraper_floor():
    for e in ent.all_tiers():
        assert e.interval_floor(fast=True) >= settings.scraper_hard_min_interval_seconds
        assert e.interval_floor(fast=False) >= e.interval_floor(fast=True)


def test_legacy_tiers_map_to_their_meaning():
    assert ent.for_tier(SubscriptionTier.PREMIUM).tier is SubscriptionTier.PRO
    assert ent.for_tier(SubscriptionTier.ULTIMATE).tier is SubscriptionTier.UNLIMITED
    assert ent.next_tier(SubscriptionTier.FREE) is SubscriptionTier.STARTER
    assert ent.next_tier(SubscriptionTier.UNLIMITED) is None


def test_requests_per_minute_reflects_fast_slots():
    pro = ent.for_tier(SubscriptionTier.PRO)
    # 10 fast slots at 60s = 10/min, 20 more rules at 300s = 4/min.
    assert pro.requests_per_minute(30) == pytest.approx(10 + 20 * 60 / 300)
    free = ent.for_tier(SubscriptionTier.FREE)
    assert free.requests_per_minute(3) == pytest.approx(3 * 60 / 600)


def test_features_are_per_level():
    assert not ent.for_tier(SubscriptionTier.FREE).has(ent.FEATURE_FLIP_MODE)
    assert ent.for_tier(SubscriptionTier.STARTER).has(ent.FEATURE_FLIP_MODE)
    assert ent.for_tier(SubscriptionTier.PRO).has(ent.FEATURE_EXPORT)
    assert not ent.for_tier(SubscriptionTier.PRO).has(ent.FEATURE_FORWARDING)
    assert ent.for_tier(SubscriptionTier.UNLIMITED).has(ent.FEATURE_FORWARDING)


# --- Fast slots in enforce_tier_limits --------------------------------------------------
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
            tables=[Base.metadata.tables["users"], Base.metadata.tables["search_rules"]],
        )


def test_fast_slots_are_limited_and_the_rest_run_at_base_interval(sqlite_db):
    async def scenario() -> None:
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=5, subscription=SubscriptionTier.STARTER)
            session.add(user)
            await session.flush()
            e = user.entitlements
            # Six rules all asking for the fastest interval.
            for i in range(6):
                session.add(SearchRule(user_id=user.id, name=f"r{i}", keywords=f"k{i}",
                                       interval_seconds=e.min_interval_seconds))
            await session.flush()

            paused, adjusted = await enforce_tier_limits(session, user)
            rules = sorted(
                (await session.execute(
                    __import__("sqlalchemy").select(SearchRule).where(SearchRule.user_id == user.id)
                )).scalars().all(),
                key=lambda r: r.id,
            )
            fast = [r for r in rules if r.interval_seconds == e.min_interval_seconds]
            slow = [r for r in rules if r.interval_seconds == e.base_interval_seconds]
            assert paused == 0
            assert len(fast) == e.fast_slots          # oldest rules keep the fast slots
            assert len(slow) == 6 - e.fast_slots
            assert adjusted == 6 - e.fast_slots

            # Downgrade to Free: no fast slots at all, and only 3 rules stay active.
            user.subscription = SubscriptionTier.FREE
            await session.flush()
            paused, _ = await enforce_tier_limits(session, user)
            assert paused == 6 - settings.free_max_rules
            assert all(r.interval_seconds >= settings.free_base_interval_seconds for r in rules)
        await db.dispose_engine()

    asyncio.run(scenario())


# --- Quotas ----------------------------------------------------------------------------
def test_quota_limits_follow_the_level():
    free = User(telegram_id=1, subscription=SubscriptionTier.FREE)
    dealer = User(telegram_id=2, subscription=SubscriptionTier.UNLIMITED)
    assert quota.limit_for(quota.KIND_CARDS, free) == settings.free_daily_notifications
    assert quota.limit_for(quota.KIND_PHOTO, free) == settings.free_photo_evals_per_month
    assert ent.is_unlimited(quota.limit_for(quota.KIND_CARDS, dealer))
    assert quota.upgrade_hint(quota.KIND_CARDS, free) is not None
    assert quota.upgrade_hint(quota.KIND_CARDS, dealer) is None


def test_quota_consume_fails_open_without_redis(monkeypatch):
    """A metering outage must never silence the product."""
    monkeypatch.setattr(settings, "redis_host", "127.0.0.1")
    monkeypatch.setattr(settings, "redis_port", 1)  # nothing listens here
    user = User(telegram_id=3, subscription=SubscriptionTier.FREE)
    state = asyncio.run(quota.consume(quota.KIND_QUICK, user))
    assert not state.exhausted
    assert state.limit == settings.free_quick_searches_per_day


def test_quota_state_arithmetic():
    s = quota.QuotaState(kind=quota.KIND_CARDS, used=10, limit=10)
    assert s.exhausted and s.remaining == 0 and s.window_label == "heute"
    s = quota.QuotaState(kind=quota.KIND_PHOTO, used=2, limit=-1)
    assert s.unlimited and not s.exhausted and s.window_label == "diesen Monat"
