"""Retention sweep and rule observability (SQLite in-memory).

Unbounded growth is an outage waiting to happen — on this project's own machine
it already filled a production disk. These tests pin down what the nightly
sweep must delete, what it must never touch, and that a rule records when it
ran and when it last found something.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database import session as db
from app.database.base import Base
from app.database.models import (
    Flip,
    Listing,
    Notification,
    PriceHistory,
    SearchRule,
    SiteName,
    SubscriptionTier,
    User,
)
from app.services import retention


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


async def _create_tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _owner_with_rule(session, tier: SubscriptionTier, tg: int):
    user = User(telegram_id=tg, subscription=tier)
    session.add(user)
    await session.flush()
    rule = SearchRule(
        user_id=user.id, name=f"rule-{tg}", keywords="tesla model 3",
        exclude_keywords=[], sites=[],
    )
    session.add(rule)
    await session.flush()
    return user, rule


def _listing(
    rule_id: int, ext: str, *, age_days: float, favorite: bool = False
) -> Listing:
    return Listing(
        rule_id=rule_id,
        site=SiteName.KLEINANZEIGEN,
        external_id=ext,
        fingerprint=f"fp-{ext}",
        title=f"Tesla Model 3 {ext}",
        url=f"https://example.com/{ext}",
        price=20000.0,
        is_favorite=favorite,
        created_at=_ago(age_days),
    )


async def _external_ids(session) -> set[str]:
    return set((await session.execute(select(Listing.external_id))).scalars().all())


def test_favorites_and_flip_listings_survive_the_sweep(sqlite_db):
    """Deleting a kept favourite or a purchase's source ad is unforgivable."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            _, rule = await _owner_with_rule(session, SubscriptionTier.FREE, 1)

            old = _listing(rule.id, "old", age_days=60)
            favorite = _listing(rule.id, "fav", age_days=60, favorite=True)
            bought = _listing(rule.id, "bought", age_days=60)
            recent = _listing(rule.id, "recent", age_days=1)
            session.add_all([old, favorite, bought, recent])
            await session.flush()

            session.add(
                Flip(telegram_id=1, listing_id=bought.id, title="B", buy_price=1.0)
            )
            # A flip logged by hand carries no listing_id; that NULL must not
            # turn the "not referenced" check into a blanket protection.
            session.add(
                Flip(telegram_id=1, listing_id=None, title="Manual", buy_price=1.0)
            )
            for row in (old, favorite, bought, recent):
                session.add(PriceHistory(listing_id=row.id, price=row.price))
            await session.commit()

            stats = await retention.sweep(session)

            assert stats.listings == 1
            assert stats.price_points == 1
            assert not stats.capped
            assert await _external_ids(session) == {"fav", "bought", "recent"}
            remaining = (
                await session.execute(select(PriceHistory.listing_id))
            ).scalars().all()
            assert old.id not in remaining
        await db.dispose_engine()

    asyncio.run(scenario())


def test_window_follows_the_owner_level(sqlite_db):
    """History length is something a paid level buys, so it is read per owner."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            _, free_rule = await _owner_with_rule(session, SubscriptionTier.FREE, 10)
            _, pro_rule = await _owner_with_rule(session, SubscriptionTier.PRO, 11)

            session.add_all([
                _listing(free_rule.id, "free-30d", age_days=30),
                _listing(free_rule.id, "free-2d", age_days=2),
                _listing(pro_rule.id, "pro-30d", age_days=30),
                _listing(pro_rule.id, "pro-400d", age_days=400),
            ])
            await session.commit()

            stats = await retention.sweep(session)

            # Free keeps 14 days, Pro 365: same age, different outcome.
            assert stats.listings == 2
            assert await _external_ids(session) == {"free-2d", "pro-30d"}
        await db.dispose_engine()

    asyncio.run(scenario())


def test_notifications_are_purged_with_the_same_window(sqlite_db):
    """Delivery records outlive the listings they describe if nobody sweeps."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            free_user, _ = await _owner_with_rule(session, SubscriptionTier.FREE, 20)
            pro_user, _ = await _owner_with_rule(session, SubscriptionTier.PRO, 21)

            session.add_all([
                Notification(user_id=free_user.id, title="alt", created_at=_ago(60)),
                Notification(user_id=free_user.id, title="neu", created_at=_ago(1)),
                Notification(user_id=pro_user.id, title="alt", created_at=_ago(60)),
            ])
            await session.commit()

            stats = await retention.sweep(session)

            assert stats.notifications == 1
            titles = (
                await session.execute(select(Notification.title))
            ).scalars().all()
            assert sorted(titles) == ["alt", "neu"]
        await db.dispose_engine()

    asyncio.run(scenario())


def test_sweep_is_a_noop_when_disabled(sqlite_db, monkeypatch):
    """The kill switch has to stop the sweep, not just slow it down."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            _, rule = await _owner_with_rule(session, SubscriptionTier.FREE, 30)
            session.add(_listing(rule.id, "ancient", age_days=999))
            await session.commit()

            monkeypatch.setattr(retention.settings, "retention_sweep_enabled", False)
            stats = await retention.sweep(session)

            assert stats.total == 0
            assert await _external_ids(session) == {"ancient"}
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_zero_window_is_refused(sqlite_db, monkeypatch):
    """A misconfigured window would wipe a whole level's history, irreversibly."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            _, rule = await _owner_with_rule(session, SubscriptionTier.FREE, 35)
            session.add(_listing(rule.id, "yesterday", age_days=1))
            await session.commit()

            monkeypatch.setattr(retention.settings, "free_history_days", 0)
            stats = await retention.sweep(session)

            assert stats.total == 0
            assert await _external_ids(session) == {"yesterday"}
        await db.dispose_engine()

    asyncio.run(scenario())


def test_row_budget_stops_the_sweep_and_says_how_much_is_left(sqlite_db):
    """A first run on a grown table must not delete everything in one lock.

    And the leftover has to be a number: a sweep that stops early looks exactly
    like a sweep with nothing to do unless it says what it did not reach.
    """

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            _, rule = await _owner_with_rule(session, SubscriptionTier.FREE, 40)
            for i in range(5):
                session.add(_listing(rule.id, f"old-{i}", age_days=60))
            await session.commit()

            stats = await retention.sweep(session, batch_size=2, row_limit=2)

            assert stats.listings == 2
            assert stats.capped is True
            assert stats.remaining[retention.CATEGORY_LISTINGS] == 3
            assert len(await _external_ids(session)) == 3
        await db.dispose_engine()

    asyncio.run(scenario())


def test_each_category_gets_its_own_budget(sqlite_db):
    """A listing backlog must not starve the notification cleanup.

    Both categories shared one budget once, spent in listing order, so a table
    that had grown for months meant the notifications were never reached at all
    — and those are the rows that grow fastest.
    """

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user, rule = await _owner_with_rule(session, SubscriptionTier.FREE, 41)
            for i in range(4):
                session.add(_listing(rule.id, f"old-{i}", age_days=60))
            for i in range(4):
                session.add(
                    Notification(
                        user_id=user.id,
                        title=f"note-{i}",
                        is_sent=True,
                        created_at=_ago(60),
                    )
                )
            await session.commit()

            stats = await retention.sweep(session, batch_size=2, row_limit=2)

            # The listing budget ran out after 2 rows — and the notifications
            # still got their own 2.
            assert stats.listings == 2
            assert stats.notifications == 2
            assert stats.remaining[retention.CATEGORY_LISTINGS] == 2
            assert stats.remaining[retention.CATEGORY_NOTIFICATIONS] == 2
        await db.dispose_engine()

    asyncio.run(scenario())


def test_rule_stats_are_written_on_a_run(sqlite_db, monkeypatch):
    """"Last checked 3 min ago" is only honest if every run stamps the rule."""
    from app.parsers.schemas import ParsedListing
    from app.services.search_service import SearchService

    posted_at = datetime.now(timezone.utc) - timedelta(minutes=7)

    async def fake_collect(self, rule, query):  # noqa: ANN001
        return [
            ParsedListing(
                site=SiteName.KLEINANZEIGEN,
                external_id="900001",
                title="Tesla Model 3 Performance",
                url="https://example.com/900001",
                price=20000.0,
                posted_at=posted_at,
            )
        ]

    monkeypatch.setattr(SearchService, "_collect", fake_collect)

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            _, rule = await _owner_with_rule(session, SubscriptionTier.FREE, 50)
            rule_id = rule.id
            await SearchService(session).run_rule(rule)
            await session.commit()

        async with maker() as session:
            rule = await session.get(SearchRule, rule_id)
            assert rule.run_count == 1
            assert rule.last_run_at is not None
            assert rule.last_found_at is not None
            first_found = rule.last_found_at

            stored = (await session.execute(select(Listing))).scalars().all()
            assert len(stored) == 1
            # The parsed posting time is what makes the latency line on a card
            # a fact instead of a guess, so it has to reach the column.
            assert stored[0].posted_at is not None

            # Same ad again: the run still counts, the "found" stamp must not.
            await SearchService(session).run_rule(rule)
            await session.commit()
            assert rule.run_count == 2
            assert rule.last_found_at == first_found
        await db.dispose_engine()

    asyncio.run(scenario())
