"""End-to-end deduplication test: the same ad must never be sent twice.

Reproduces the user's report ("bot keeps sending the same offers") by running
the FULL SearchService.run_rule pipeline twice against an in-memory database
with a stubbed parser that returns identical listings each time.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import SearchRule, SubscriptionTier, User
from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing
from app.services.search_service import SearchService


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


def _listing(ext_id: str, price: float, title: str = "Tesla Model 3 Performance"):
    # Fresh posting so the freshness filter always lets it through.
    from datetime import datetime

    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id=ext_id,
        title=title,
        url=f"https://www.kleinanzeigen.de/s-anzeige/{ext_id}",
        price=price,
        posted_at=datetime.now(),
    )


async def _make_rule(session) -> SearchRule:
    user = User(telegram_id=1, subscription=SubscriptionTier.FREE)
    session.add(user)
    await session.flush()
    rule = SearchRule(
        user_id=user.id, name="Tesla", keywords="tesla model 3",
        exclude_keywords=[], sites=[], interval_seconds=300, min_deal_score=0,
    )
    session.add(rule)
    await session.flush()
    return rule


def test_same_ads_not_returned_on_second_run(sqlite_db, monkeypatch):
    batch = [
        _listing("100001", 30000),
        _listing("100002", 28000),
        _listing("100003", 26000),
    ]

    async def fake_collect(self, query):  # noqa: ANN001
        # Every scrape returns the exact same ads (like a quiet marketplace).
        return list(batch)

    monkeypatch.setattr(
        "app.parsers.base.BaseParser.collect", fake_collect, raising=True
    )

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = db.get_sessionmaker()

        async with maker() as session:
            rule = await _make_rule(session)
            first = await SearchService(session).run_rule(rule)
            await session.commit()
        # First run: all three ads are new.
        assert len(first) == 3

        async with maker() as session:
            rule = await session.get(SearchRule, rule.id)
            second = await SearchService(session).run_rule(rule)
            await session.commit()
        # Second run with identical ads: NOTHING new must be returned.
        assert second == [], f"duplicate delivery! got {len(second)} again"

        # And no duplicate rows were created in the database.
        from sqlalchemy import func, select

        from app.database.models import Listing

        async with maker() as session:
            count = await session.scalar(select(func.count(Listing.id)))
        assert count == 3, f"expected 3 stored listings, found {count}"

        await db.dispose_engine()

    asyncio.run(scenario())


def test_price_drop_renotifies_but_only_once(sqlite_db, monkeypatch):
    state = {"batch": [_listing("200001", 30000)]}

    async def fake_collect(self, query):  # noqa: ANN001
        return list(state["batch"])

    monkeypatch.setattr(
        "app.parsers.base.BaseParser.collect", fake_collect, raising=True
    )

    async def scenario() -> None:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = db.get_sessionmaker()

        async with maker() as session:
            rule = await _make_rule(session)
            first = await SearchService(session).run_rule(rule)
            await session.commit()
        assert len(first) == 1

        # Price drops by 3000 -> one re-notification.
        state["batch"] = [_listing("200001", 27000)]
        async with maker() as session:
            rule = await session.get(SearchRule, rule.id)
            second = await SearchService(session).run_rule(rule)
            await session.commit()
        assert len(second) == 1, "a real price drop should re-notify"

        # Same (now lower) price again -> no further notification.
        async with maker() as session:
            rule = await session.get(SearchRule, rule.id)
            third = await SearchService(session).run_rule(rule)
            await session.commit()
        assert third == [], "an unchanged price must not re-notify"

        await db.dispose_engine()

    asyncio.run(scenario())
