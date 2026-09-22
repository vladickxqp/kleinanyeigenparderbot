"""Blocking a seller, not just one of their ads.

The 🙈 button hides a single listing — the wrong tool against a dealer with
two hundred cars. These tests pin down the two things that decide whether a
block keeps working: it is keyed on the marketplace's own seller id (a dealer
can rename itself), and an ad that names no seller is never dropped by it,
because most marketplaces name none and dropping those would empty the rule
everywhere at once.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import SiteName, User
from app.parsers.schemas import ParsedListing
from app.services import blocked_sellers


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


def _run(scenario):
    async def wrapper():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=700)
            session.add(user)
            await session.flush()
            result = await scenario(session, user)
        await db.dispose_engine()
        return result

    return asyncio.run(wrapper())


def _ad(ext: str, *, seller_id=None, seller_name=None,
        site=SiteName.AUTOSCOUT24) -> ParsedListing:
    return ParsedListing(
        site=site, external_id=ext, title="Tesla Model 3",
        url=f"https://example.com/{ext}", price=20000.0,
        seller_id=seller_id, seller_name=seller_name,
    )


# --- The key ----------------------------------------------------------------------
def test_the_id_wins_over_the_name():
    # A dealer can rename itself overnight; the id does not move.
    assert blocked_sellers.seller_key("3129868", "Exclusive Cars GmbH") == "3129868"


def test_a_name_is_used_when_there_is_no_id():
    assert blocked_sellers.seller_key(None, "  Exclusive   Cars  ") == "exclusive cars"


def test_an_ad_without_a_seller_cannot_be_blocked():
    assert blocked_sellers.seller_key(None, None) is None
    assert blocked_sellers.can_block(None, None) is False
    assert blocked_sellers.can_block(None, "Autohaus Meier") is True


# --- Blocking and lifting ----------------------------------------------------------
def test_blocking_a_seller_sticks(sqlite_db):
    async def scenario(session, user):
        await blocked_sellers.block(
            session, user.id, SiteName.AUTOSCOUT24,
            seller_id="3129868", seller_name="Exclusive Cars GmbH",
        )
        return await blocked_sellers.blocked_keys(session, user.id)

    assert _run(scenario) == {("autoscout24", "3129868")}


def test_blocking_twice_is_not_an_error(sqlite_db):
    async def scenario(session, user):
        for _ in range(2):
            await blocked_sellers.block(
                session, user.id, SiteName.AUTOSCOUT24,
                seller_id="1", seller_name="A",
            )
        return len(await blocked_sellers.listed(session, user.id))

    assert _run(scenario) == 1


def test_an_ad_that_names_nobody_blocks_nobody(sqlite_db):
    async def scenario(session, user):
        result = await blocked_sellers.block(
            session, user.id, SiteName.KLEINANZEIGEN,
            seller_id=None, seller_name=None,
        )
        return result, await blocked_sellers.blocked_keys(session, user.id)

    result, keys = _run(scenario)
    assert result is None and keys == set()


def test_a_block_can_be_lifted(sqlite_db):
    async def scenario(session, user):
        await blocked_sellers.block(
            session, user.id, SiteName.AUTOSCOUT24, seller_id="7", seller_name="X",
        )
        lifted = await blocked_sellers.unblock(
            session, user.id, SiteName.AUTOSCOUT24, "7"
        )
        return lifted, await blocked_sellers.blocked_keys(session, user.id)

    lifted, keys = _run(scenario)
    assert lifted is True and keys == set()


def test_blocks_do_not_leak_between_users(sqlite_db):
    async def scenario(session, user):
        other = User(telegram_id=701)
        session.add(other)
        await session.flush()
        await blocked_sellers.block(
            session, other.id, SiteName.AUTOSCOUT24, seller_id="9", seller_name="Y",
        )
        return await blocked_sellers.blocked_keys(session, user.id)

    assert _run(scenario) == set()


# --- What the pipeline drops --------------------------------------------------------
def test_only_the_blocked_seller_s_ads_are_dropped():
    blocked = {("autoscout24", "3129868")}
    items = [
        _ad("a", seller_id="3129868", seller_name="Exclusive Cars"),
        _ad("b", seller_id="999", seller_name="Anderes Autohaus"),
    ]
    kept = blocked_sellers.drop_blocked(items, blocked)
    assert [i.external_id for i in kept] == ["b"]


def test_an_ad_without_a_seller_survives_every_block():
    # Kleinanzeigen and eBay name no seller on the result card. Dropping those
    # would empty the rule on every marketplace but AutoScout24.
    blocked = {("autoscout24", "3129868"), ("kleinanzeigen", "irgendwer")}
    items = [_ad("k", site=SiteName.KLEINANZEIGEN)]
    assert blocked_sellers.drop_blocked(items, blocked) == items


def test_a_block_on_one_site_does_not_reach_another():
    blocked = {("kleinanzeigen", "3129868")}
    items = [_ad("a", seller_id="3129868", seller_name="Exclusive Cars")]
    # Same key, different marketplace — a coincidence, not the same seller.
    assert blocked_sellers.drop_blocked(items, blocked) == items


def test_nothing_blocked_means_nothing_is_touched():
    items = [_ad("a", seller_id="1"), _ad("b", seller_id="2")]
    assert blocked_sellers.drop_blocked(items, set()) is items


def test_the_pipeline_drops_them_before_the_price_statistics():
    """A silenced dealer must not keep shaping what counts as a good deal."""
    import inspect

    from app.services import search_service

    source = inspect.getsource(search_service.SearchService.run_rule)
    assert "drop_blocked" in source
    # Before the relevance filter, which is before the statistics.
    assert source.index("drop_blocked") < source.index("filter_relevant")
