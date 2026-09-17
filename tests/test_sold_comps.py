"""Realised prices inferred from ads that stopped appearing.

Every other price in this bot is an asking price. These comparables are the
only ones that reflect what a buyer actually paid, which makes them worth more
than the rest — and makes a wrong one worse than none, because it moves the
median the deal score is measured against. The tests below are mostly about the
guards that keep a bad inference out.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database import session as db
from app.database.base import Base
from app.database.models import Listing, SearchRule, SiteName, User
from app.services import sold_comps


class FakeRedis:
    """The hash commands this module uses, in memory.

    A double rather than a live server: these tests have to run in CI, and the
    point here is the decision logic, not Redis itself.
    """

    def __init__(self, *, broken: bool = False) -> None:
        self.data: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}
        self.broken = broken

    def _check(self) -> None:
        if self.broken:
            raise ConnectionError("redis is down")

    async def hkeys(self, key):  # noqa: ANN001
        self._check()
        return list(self.data.get(key, {}))

    async def hgetall(self, key):  # noqa: ANN001
        self._check()
        return dict(self.data.get(key, {}))

    async def hset(self, key, field, value):  # noqa: ANN001
        self._check()
        self.data.setdefault(key, {})[str(field)] = str(value)

    async def hdel(self, key, *fields):  # noqa: ANN001
        self._check()
        bucket = self.data.get(key, {})
        for field in fields:
            bucket.pop(str(field), None)

    async def hincrby(self, key, field, amount=1):  # noqa: ANN001
        self._check()
        bucket = self.data.setdefault(key, {})
        bucket[str(field)] = str(int(bucket.get(str(field), 0)) + amount)
        return int(bucket[str(field)])

    async def expire(self, key, ttl):  # noqa: ANN001
        self._check()
        self.expires[key] = ttl

    async def keys(self, pattern):  # noqa: ANN001
        self._check()
        prefix = pattern.rstrip("*")
        return [key for key in self.data if key.startswith(prefix)]

    async def aclose(self) -> None:
        return None


@pytest.fixture()
def fake_redis(monkeypatch):
    """Point the module at an in-memory store instead of a server."""
    client = FakeRedis()

    @asynccontextmanager
    async def _redis():
        yield client

    monkeypatch.setattr(sold_comps, "_redis", _redis)
    return client


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


async def _tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


async def _rule_with_listings(session, specs) -> int:
    """``specs`` = list of (external_id, price, age_days)."""
    user = User(telegram_id=900)
    session.add(user)
    await session.flush()
    rule = SearchRule(
        user_id=user.id, name="cars", keywords="tesla model 3",
        exclude_keywords=[], sites=[],
    )
    session.add(rule)
    await session.flush()
    for ext, price, age_days in specs:
        session.add(
            Listing(
                rule_id=rule.id,
                site=SiteName.KLEINANZEIGEN,
                external_id=ext,
                fingerprint=f"fp-{ext}",
                title=f"Tesla Model 3 {ext}",
                url=f"https://example.com/{ext}",
                price=price,
                created_at=NOW - timedelta(days=age_days),
            )
        )
    await session.commit()
    return rule.id


def _seen(*external_ids: str):
    return [(SiteName.KLEINANZEIGEN, ext) for ext in external_ids]


def _run(scenario):
    """Run one async scenario against a fresh in-memory database."""

    async def wrapper():
        await _tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            await scenario(session)
        await db.dispose_engine()

    asyncio.run(wrapper())


# --- The guards ------------------------------------------------------------------
def test_a_run_that_saw_nothing_is_not_evidence_of_anything(sqlite_db, fake_redis):
    """A blocked parser looks exactly like a market that sold out overnight."""

    async def scenario(session):
        rule_id = await _rule_with_listings(session, [("a", 100.0, 1), ("b", 200.0, 1)])
        result = await sold_comps.observe_run(session, rule_id, [], now=NOW)
        assert result.counted is False
        assert result.missing == 0
        # Nothing was written at all — not even a miss counter.
        assert fake_redis.data == {}

    _run(scenario)


def test_an_ad_must_disappear_repeatedly_before_it_counts_as_sold(
    sqlite_db, fake_redis, monkeypatch
):
    monkeypatch.setattr(sold_comps.settings, "sold_comp_missing_runs", 3)

    async def scenario(session):
        rule_id = await _rule_with_listings(session, [("a", 100.0, 1), ("b", 200.0, 1)])
        # "b" is gone from every run; one miss is not a sale.
        for expected_sold in (0, 0, 1):
            result = await sold_comps.observe_run(
                session, rule_id, _seen("a"), now=NOW
            )
            assert result.sold == expected_sold
            assert result.seen == 1 and result.missing == 1

        comps = await sold_comps.realised_comps(rule_id, now=NOW)
        assert [comp.price for comp in comps] == [200.0]

    _run(scenario)


def test_an_ad_that_comes_back_starts_counting_from_zero(
    sqlite_db, fake_redis, monkeypatch
):
    """One paginated result page or one hiccup must not add up over a week."""
    monkeypatch.setattr(sold_comps.settings, "sold_comp_missing_runs", 3)

    async def scenario(session):
        rule_id = await _rule_with_listings(session, [("a", 100.0, 1), ("b", 200.0, 1)])
        await sold_comps.observe_run(session, rule_id, _seen("a"), now=NOW)
        await sold_comps.observe_run(session, rule_id, _seen("a"), now=NOW)
        # "b" is back — the two misses are void.
        await sold_comps.observe_run(session, rule_id, _seen("a", "b"), now=NOW)
        result = await sold_comps.observe_run(session, rule_id, _seen("a"), now=NOW)
        assert result.sold == 0
        assert await sold_comps.realised_comps(rule_id, now=NOW) == []

    _run(scenario)


def test_an_old_ad_that_vanishes_is_not_called_a_sale(
    sqlite_db, fake_redis, monkeypatch
):
    """After weeks an ad is as likely withdrawn, expired or edited out."""
    monkeypatch.setattr(sold_comps.settings, "sold_comp_missing_runs", 1)
    monkeypatch.setattr(sold_comps.settings, "sold_comp_max_age_days", 45)

    async def scenario(session):
        rule_id = await _rule_with_listings(
            session, [("fresh", 100.0, 2), ("ancient", 200.0, 90), ("anchor", 50.0, 1)]
        )
        result = await sold_comps.observe_run(session, rule_id, _seen("anchor"), now=NOW)
        assert result.sold == 1
        assert [comp.price for comp in await sold_comps.realised_comps(rule_id, now=NOW)] == [
            100.0
        ]

    _run(scenario)


def test_an_ad_without_a_price_is_not_a_comparable(sqlite_db, fake_redis, monkeypatch):
    monkeypatch.setattr(sold_comps.settings, "sold_comp_missing_runs", 1)

    async def scenario(session):
        rule_id = await _rule_with_listings(
            session, [("free", None, 1), ("zero", 0.0, 1), ("anchor", 50.0, 1)]
        )
        result = await sold_comps.observe_run(session, rule_id, _seen("anchor"), now=NOW)
        assert result.missing == 2 and result.sold == 0

    _run(scenario)


def test_a_sale_is_booked_once_and_never_refreshed(sqlite_db, fake_redis, monkeypatch):
    """Otherwise every later run re-dates the sale and it never ages out."""
    monkeypatch.setattr(sold_comps.settings, "sold_comp_missing_runs", 1)

    async def scenario(session):
        rule_id = await _rule_with_listings(session, [("a", 100.0, 1), ("b", 200.0, 1)])
        first = await sold_comps.observe_run(session, rule_id, _seen("a"), now=NOW)
        assert first.sold == 1
        sold_at = (await sold_comps.realised_comps(rule_id, now=NOW))[0].sold_at

        later = NOW + timedelta(days=10)
        again = await sold_comps.observe_run(session, rule_id, _seen("a"), now=later)
        assert again.sold == 0
        assert again.missing == 0  # already settled, not missing any more
        assert (await sold_comps.realised_comps(rule_id, now=later))[0].sold_at == sold_at

    _run(scenario)


# --- Reading the comparables -----------------------------------------------------
def test_comparables_are_newest_first_and_expire(sqlite_db, fake_redis, monkeypatch):
    monkeypatch.setattr(sold_comps.settings, "sold_comp_max_age_days", 45)

    async def scenario(session):
        key = sold_comps.SOLD_KEY.format(rule_id=7)
        old = int((NOW - timedelta(days=60)).timestamp())
        recent = int((NOW - timedelta(days=1)).timestamp())
        older = int((NOW - timedelta(days=20)).timestamp())
        fake_redis.data[key] = {
            "1": f"100.0|{old}",
            "2": f"200.0|{recent}",
            "3": f"300.0|{older}",
            "4": "kaputt",
        }
        comps = await sold_comps.realised_comps(7, now=NOW)
        # The 60-day-old sale and the unreadable row are both gone.
        assert [comp.price for comp in comps] == [200.0, 300.0]

    _run(scenario)


def test_realised_stats_describe_what_actually_sold(sqlite_db, fake_redis):
    async def scenario(session):
        key = sold_comps.SOLD_KEY.format(rule_id=8)
        stamp = int((NOW - timedelta(days=1)).timestamp())
        fake_redis.data[key] = {
            str(i): f"{price}|{stamp}"
            for i, price in enumerate([1000.0, 1200.0, 1400.0], start=1)
        }
        stats = await sold_comps.realised_stats(8, now=NOW)
        assert stats.count == 3
        assert stats.median == 1200.0
        # This is the number a deal is measured against, so it has to be the
        # realised one rather than what the remaining sellers still hope for.
        assert stats.discount_percent(900.0) == 25.0

    _run(scenario)


# --- Housekeeping ----------------------------------------------------------------
def test_prune_drops_stale_sales_and_counters_of_deleted_listings(
    sqlite_db, fake_redis, monkeypatch
):
    """The keys carry a TTL, but a busy rule keeps refreshing the whole key."""
    monkeypatch.setattr(sold_comps.settings, "sold_comp_max_age_days", 45)

    async def scenario(session):
        rule_id = await _rule_with_listings(session, [("a", 100.0, 1)])
        alive_id = await session.scalar(
            select(Listing.id).where(Listing.rule_id == rule_id)
        )

        sold_key = sold_comps.SOLD_KEY.format(rule_id=rule_id)
        missing_key = sold_comps.MISSING_KEY.format(rule_id=rule_id)
        fake_redis.data[sold_key] = {
            "1": f"100.0|{int((NOW - timedelta(days=60)).timestamp())}",
            "2": f"200.0|{int((NOW - timedelta(days=1)).timestamp())}",
        }
        fake_redis.data[missing_key] = {str(alive_id): "1", "999999": "2"}

        removed = await sold_comps.prune(session, now=NOW)
        assert removed == 2
        assert list(fake_redis.data[sold_key]) == ["2"]
        # The counter of the listing that still exists survives; the orphan does not.
        assert list(fake_redis.data[missing_key]) == [str(alive_id)]

    _run(scenario)


# --- Failure modes ---------------------------------------------------------------
def test_redis_trouble_never_breaks_the_search_run(sqlite_db, monkeypatch):
    broken = FakeRedis(broken=True)

    @asynccontextmanager
    async def _redis():
        yield broken

    monkeypatch.setattr(sold_comps, "_redis", _redis)

    async def scenario(session):
        rule_id = await _rule_with_listings(session, [("a", 100.0, 1)])
        # A bookkeeping outage costs data points, never the user's deals.
        result = await sold_comps.observe_run(session, rule_id, _seen("a"), now=NOW)
        assert result.sold == 0
        assert await sold_comps.realised_comps(rule_id, now=NOW) == []
        assert await sold_comps.prune(session, now=NOW) == 0

    _run(scenario)


def test_the_whole_feature_can_be_switched_off(sqlite_db, fake_redis, monkeypatch):
    monkeypatch.setattr(sold_comps.settings, "sold_comps_enabled", False)

    async def scenario(session):
        rule_id = await _rule_with_listings(session, [("a", 100.0, 1), ("b", 200.0, 1)])
        result = await sold_comps.observe_run(session, rule_id, _seen("a"), now=NOW)
        assert result.counted is False
        assert fake_redis.data == {}
        assert await sold_comps.realised_comps(rule_id, now=NOW) == []
        assert sold_comps.watch(SimpleNamespace(_collect=None)) == []

    _run(scenario)


# --- Observing the pipeline -------------------------------------------------------
def test_watch_records_what_the_run_actually_saw():
    """The scrape step has no hook of its own, so it is wrapped."""
    collected = [
        SimpleNamespace(site=SiteName.KLEINANZEIGEN, external_id="a"),
        SimpleNamespace(site=SiteName.KLEINANZEIGEN, external_id=""),
        SimpleNamespace(site=SiteName.EBAY, external_id="b"),
    ]

    async def _collect(rule, query):  # noqa: ANN001
        return collected

    service = SimpleNamespace(_collect=_collect)
    seen = sold_comps.watch(service)
    assert asyncio.run(service._collect(None, None)) is collected
    # The id-less entry is dropped: it identifies nothing to miss later.
    assert seen == [(SiteName.KLEINANZEIGEN, "a"), (SiteName.EBAY, "b")]


def test_watch_leaves_a_pipeline_it_does_not_recognise_alone():
    # A missing sold comparable costs one data point; a broken search run costs
    # the user their deal.
    assert sold_comps.watch(SimpleNamespace()) == []
