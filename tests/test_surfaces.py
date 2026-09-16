"""The surfaces that sell the plan model: /premium, /usage and the Mini App.

Every figure on these screens must come from settings — a comparison table that
drifts from the enforced entitlements is worse than none at all.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.bot.handlers import premium as premium_view
from app.bot.handlers import usage as usage_view
from app.config.settings import settings
from app.database import session as db
from app.database.base import Base
from app.database.models import SubscriptionTier, User
from app.services import entitlements as ent
from app.services import quota


def _user(tier: SubscriptionTier = SubscriptionTier.FREE) -> User:
    return User(telegram_id=4711, subscription=tier, language_code="de")


# --- /premium comparison --------------------------------------------------------------
def test_comparison_shows_all_four_levels_and_marks_the_current_one():
    text = premium_view._comparison_text(_user(SubscriptionTier.PRO), "de")
    for e in ent.all_tiers():
        assert f"<b>{e.label}</b>" in text
    marker = premium_view.t("premium.compare_current", "de")
    assert text.count(marker) == 1
    profi = ent.for_tier(SubscriptionTier.PRO)
    assert f"<b>{profi.label}</b>" in text.split(marker)[0]


def test_comparison_numbers_follow_settings(monkeypatch):
    """Proof that nothing is hardcoded: move the dials, watch the table move."""
    monkeypatch.setattr(settings, "pro_max_rules", 4242)
    monkeypatch.setattr(settings, "pro_fast_slots", 7)
    monkeypatch.setattr(settings, "pro_daily_notifications", 1234)
    monkeypatch.setattr(settings, "starter_history_days", 99)

    text = premium_view._comparison_text(_user(), "de")
    assert "4242" in text and "7" in text and "1234" in text and "99 Tage" in text


def test_comparison_renders_unlimited_quotas_as_words():
    text = premium_view._comparison_text(_user(SubscriptionTier.UNLIMITED), "de")
    assert ent.fmt_quota(ent.UNLIMITED) in text
    assert "-1" not in text


def test_comparison_lists_what_each_level_adds():
    text = premium_view._comparison_text(_user(), "de")
    for feature in ent.for_tier(SubscriptionTier.UNLIMITED).features:
        assert premium_view.feature_label(feature, "de") in text
    # A level only claims what it adds, never what it inherited.
    assert text.count(premium_view.feature_label(ent.FEATURE_FLIP_MODE, "de")) == 1


def test_dealer_plan_explains_itself_when_it_is_not_on_sale(monkeypatch):
    monkeypatch.setattr(settings, "dealer_requires_proxies", True)
    monkeypatch.setattr(settings, "scraper_proxies", "")
    assert not premium_view.premium.dealer_on_sale()

    dealer = ent.for_tier(SubscriptionTier.UNLIMITED)
    text = premium_view._premium_text(_user(), None, "", "de")
    # The level stays in the comparison, with one line saying why you can't buy it.
    assert f"<b>{dealer.label}</b>" in text
    assert premium_view.t("premium.not_bookable", "de", plan=dealer.label) in text


# --- /usage -----------------------------------------------------------------------------
def _states(**limits: int) -> dict[str, quota.QuotaState]:
    used = {quota.KIND_CARDS: 9, quota.KIND_QUICK: 3, quota.KIND_PHOTO: 2, quota.KIND_NEGO: 0}
    return {
        kind: quota.QuotaState(kind=kind, used=used[kind], limit=limits[kind])
        for kind in used
    }


def test_usage_block_handles_unlimited_and_exhausted_side_by_side():
    states = _states(
        cards=9,                  # exactly at the cap
        quick=10,                 # room left
        photo=ent.UNLIMITED,      # no cap at all
        nego=0,                   # a level that does not include this at all
    )
    text = usage_view.quota_block(states, "de")

    assert usage_view.t("usage.row_exhausted", "de", bar="", used=9, limit=9).strip() in text
    assert "7 übrig" in text
    assert usage_view.t("usage.row_unlimited", "de", used=2) in text
    # Every kind is named, none silently dropped.
    for kind in (quota.KIND_CARDS, quota.KIND_QUICK, quota.KIND_PHOTO, quota.KIND_NEGO):
        assert usage_view.t(f"usage.kind.{kind}", "de") in text
    assert "-1" not in text


def test_usage_bar_is_honest_at_the_edges():
    full = usage_view._bar(quota.QuotaState(kind=quota.KIND_CARDS, used=10, limit=10))
    empty = usage_view._bar(quota.QuotaState(kind=quota.KIND_CARDS, used=0, limit=500))
    barely = usage_view._bar(quota.QuotaState(kind=quota.KIND_CARDS, used=1, limit=500))
    none_allowed = usage_view._bar(quota.QuotaState(kind=quota.KIND_PHOTO, used=0, limit=0))

    assert full == usage_view._BAR_FULL * usage_view._BAR_CELLS
    assert empty == usage_view._BAR_EMPTY * usage_view._BAR_CELLS
    assert barely.startswith(usage_view._BAR_FULL)  # a single hit must be visible
    assert none_allowed == usage_view._BAR_FULL * usage_view._BAR_CELLS


def test_upgrade_nudge_is_worded_by_the_quota_service_and_stops_at_the_top():
    user = _user()
    states = _states(cards=9, quick=10, photo=1, nego=3)
    nudge = usage_view.upgrade_nudge(user, "de", states)
    assert nudge is not None
    # The exhausted quota is the one on offer, in quota.upgrade_hint's own words.
    assert quota.upgrade_hint(quota.KIND_CARDS, user) in nudge
    assert usage_view.upgrade_nudge(_user(SubscriptionTier.UNLIMITED), "de", states) is None


def test_premium_and_usage_share_one_upgrade_wording():
    user = _user()
    states = _states(cards=9, quick=10, photo=1, nego=3)
    nudge = usage_view.upgrade_nudge(user, "de", states)
    assert nudge is not None
    assert nudge in premium_view._premium_text(user, None, "", "de", nudge)


# --- Mini App payload -------------------------------------------------------------------
@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


def test_webapp_me_carries_entitlements_and_the_quota_snapshot(sqlite_db, monkeypatch):
    # Nothing listens here: the payload must still be complete (quotas fail open).
    monkeypatch.setattr(settings, "redis_host", "127.0.0.1")
    monkeypatch.setattr(settings, "redis_port", 1)
    from app.api.routers import webapp as webapp_api

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    Base.metadata.tables["users"],
                    Base.metadata.tables["subscriptions"],
                    Base.metadata.tables["payments"],
                ],
            )
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = _user(SubscriptionTier.STARTER)
            session.add(user)
            await session.flush()

            payload = await webapp_api.me(user=user, session=session)

        assert {q.kind for q in payload.usage} == {
            quota.KIND_CARDS, quota.KIND_PHOTO, quota.KIND_QUICK, quota.KIND_NEGO
        }
        cards = next(q for q in payload.usage if q.kind == quota.KIND_CARDS)
        assert cards.limit == settings.starter_daily_notifications
        assert cards.used == 0 and cards.label and cards.window

        starter = ent.for_tier(SubscriptionTier.STARTER)
        assert payload.entitlements.tier == starter.tier.value
        assert payload.entitlements.max_rules == starter.max_rules
        assert [lvl.tier for lvl in payload.levels] == [e.tier.value for e in ent.all_tiers()]
        assert payload.levels[0].price_stars == 0        # Free is not for sale
        assert not payload.levels[0].purchasable
        await db.dispose_engine()

    asyncio.run(scenario())


# --- Admin dashboard --------------------------------------------------------------------
def test_dashboard_counts_levels_and_card_quota_pressure(sqlite_db):
    from sqlalchemy import select

    from app.bot.handlers.admin import _tier_pressure
    from app.database.models import Listing, SearchRule, SiteName

    free_limit = settings.free_daily_notifications

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    Base.metadata.tables["users"],
                    Base.metadata.tables["search_rules"],
                    Base.metadata.tables["listings"],
                ],
            )
        maker = db.get_sessionmaker()
        async with maker() as session:
            # One user per level, plus a legacy value that must fold into Profi.
            for i, tier in enumerate(
                (SubscriptionTier.FREE, SubscriptionTier.FREE, SubscriptionTier.STARTER,
                 SubscriptionTier.PRO, SubscriptionTier.UNLIMITED, SubscriptionTier.PREMIUM)
            ):
                session.add(User(telegram_id=100 + i, subscription=tier))
            await session.flush()

            users = (await session.execute(select(User))).scalars().all()
            hungry, halfway = users[0], users[1]
            for owner, cards in ((hungry, free_limit), (halfway, free_limit - 1)):
                rule = SearchRule(user_id=owner.id, name="r", keywords="k")
                session.add(rule)
                await session.flush()
                for n in range(cards):
                    session.add(
                        Listing(
                            rule_id=rule.id, site=SiteName.KLEINANZEIGEN,
                            external_id=f"{owner.id}-{n}", fingerprint=f"{owner.id}-{n}",
                            title="x", url="https://example.test",
                            notified=True, notified_at=datetime.now(timezone.utc),
                        )
                    )
            await session.flush()

            labels, near, at_limit, _ = await _tier_pressure(session)

        assert labels.count("<b>2</b>") == 2       # two on Free, two on Profi (one legacy)
        for e in ent.all_tiers():
            assert e.label in labels
        assert at_limit == 1                       # the user who used the whole day's cards
        assert near == 1                           # the one a single card short of it
        await db.dispose_engine()

    asyncio.run(scenario())
