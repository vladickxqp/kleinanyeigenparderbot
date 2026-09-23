"""A whole device is never priced off a pile of spare displays.

On a defect hunt the spare-part ads are kept on purpose — they are what a
repairer looks for. They are held out of the market sample because a loose
display costs a fraction of a whole broken phone, and letting those prices
into the median drags the reference down to fragment level.

The hold-out had a floor: below three whole-unit prices the parts were poured
back in. That is the ordinary shape of a phone search — two whole devices
among six displays — and the merged median then landed in the part cluster.
Every whole device was measured against 40 € fragments, scored OVERPRICED and
dropped before the user ever saw it. A missed deal leaves nothing behind to
notice, which is why this went unseen.

These tests pin both edges down: the two groups are never merged to reach a
minimum size, and a part with no comparable parts gets no verdict at all
rather than one borrowed from whole devices.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import SearchRule, SubscriptionTier, User
from app.database.models.enums import Condition, DealVerdict, SiteName
from app.parsers.schemas import ParsedListing
from app.services.price_analysis import compute_price_stats
from app.services.search_service import (
    MIN_PART_PRICES,
    SearchService,
    split_part_prices,
)

WHOLE = "iPhone 14 Pro defekt"
PART = "iPhone 14 Pro Display Ersatzteil"


def _ad(ext: str, title: str, price: float) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN, external_id=ext, title=title,
        url=f"https://example.com/{ext}", price=price, posted_at=datetime.now(),
    )


# --- The split itself ---------------------------------------------------------------
def test_two_whole_devices_are_not_drowned_in_six_displays():
    """The regression: the merge used to hand back one mixed pile."""
    batch = [_ad("w1", WHOLE, 700.0), _ad("w2", WHOLE, 750.0)] + [
        _ad(f"p{i}", PART, 40.0) for i in range(6)
    ]
    whole, parts = split_part_prices(batch)
    assert whole == [700.0, 750.0]
    assert parts == [40.0] * 6


def test_the_median_a_device_is_judged_against_is_a_device_price():
    batch = [_ad("w1", WHOLE, 700.0), _ad("w2", WHOLE, 750.0)] + [
        _ad(f"p{i}", PART, 40.0) for i in range(6)
    ]
    whole, _ = split_part_prices(batch)
    # Used to be 40.0 — a phone measured against a spare screen.
    assert compute_price_stats(whole).median == 725.0


def test_a_single_whole_device_still_counts_as_the_whole_market():
    """Thin is the honest answer; the scorer already shrinks a thin verdict."""
    batch = [_ad("w1", WHOLE, 700.0)] + [_ad(f"p{i}", PART, 40.0) for i in range(6)]
    whole, parts = split_part_prices(batch)
    assert whole == [700.0]
    assert len(parts) == 6


def test_a_parts_only_rule_still_gets_a_market():
    """Nothing whole was found, so the parts ARE what was asked about."""
    batch = [_ad(f"p{i}", PART, 40.0 + i) for i in range(4)]
    whole, parts = split_part_prices(batch)
    assert whole == [40.0, 41.0, 42.0, 43.0]
    assert parts == []


def test_ads_without_a_price_are_in_neither_group():
    batch = [_ad("w1", WHOLE, 700.0), _ad("w2", WHOLE, 750.0), _ad("w3", WHOLE, 800.0)]
    batch.append(
        ParsedListing(
            site=SiteName.KLEINANZEIGEN, external_id="vb", title=WHOLE,
            url="https://example.com/vb", price=None,
        )
    )
    whole, parts = split_part_prices(batch)
    assert whole == [700.0, 750.0, 800.0]
    assert parts == []


def test_an_ordinary_batch_is_unchanged():
    batch = [_ad(f"w{i}", WHOLE, 700.0 + i) for i in range(5)] + [
        _ad("p1", PART, 40.0)
    ]
    whole, parts = split_part_prices(batch)
    assert len(whole) == 5
    assert parts == [40.0]


# --- End to end ---------------------------------------------------------------------
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


def _run(batch: list[ParsedListing], monkeypatch) -> dict[str, object]:
    async def fake_collect(self, query):  # noqa: ANN001
        return list(batch)

    monkeypatch.setattr(
        "app.parsers.base.BaseParser.collect", fake_collect, raising=True
    )

    async def scenario() -> dict[str, object]:
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=42, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()
            rule = SearchRule(
                user_id=user.id, name="iphone", keywords="iphone 14 pro",
                exclude_keywords=[], sites=[], interval_seconds=300,
                min_deal_score=0, condition=Condition.DEFECTIVE,
            )
            session.add(rule)
            await session.flush()
            rows = await SearchService(session).run_rule(rule)
            result = {
                row.external_id: (row.deal_verdict, row.estimated_market_price)
                for row in rows
            }
            await session.commit()
        await db.dispose_engine()
        return result

    return asyncio.run(scenario())


def test_a_cheap_whole_device_survives_a_batch_full_of_displays(sqlite_db, monkeypatch):
    """The user-visible failure: the good one used to be scored OVERPRICED."""
    # Two whole devices is the shape that used to trigger the merge.
    batch = [
        _ad("w1", WHOLE, 700.0),
        _ad("w2", WHOLE, 400.0),  # the actual find
    ] + [_ad(f"p{i}", PART, 40.0) for i in range(6)]

    scored = _run(batch, monkeypatch)

    verdict, market = scored["w2"]
    assert market is not None and market > 300.0, market
    assert verdict is not DealVerdict.OVERPRICED


def test_a_display_is_not_announced_as_a_steal_against_phone_prices(
    sqlite_db, monkeypatch
):
    """Fewer than the minimum comparable parts means no verdict, not a jackpot."""
    batch = [_ad(f"w{i}", WHOLE, 700.0 + i * 10) for i in range(5)]
    batch += [_ad("p1", PART, 40.0)]  # one lonely display
    assert MIN_PART_PRICES > 1

    scored = _run(batch, monkeypatch)

    verdict, _ = scored["p1"]
    assert verdict is DealVerdict.UNKNOWN, verdict


def test_displays_are_judged_against_displays_once_there_are_enough(
    sqlite_db, monkeypatch
):
    batch = [_ad(f"w{i}", WHOLE, 700.0 + i * 10) for i in range(5)]
    batch += [_ad("p1", PART, 60.0), _ad("p2", PART, 65.0), _ad("p3", PART, 20.0)]

    scored = _run(batch, monkeypatch)

    _, market = scored["p3"]
    # The reference is the display market, not the 700 € phone market.
    assert market is not None and market < 100.0, market
