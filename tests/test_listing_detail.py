"""One listing, opened up: description, price history, and what it is compared to.

The deal card answers "is this cheap?" with one number, and never shows what
that number was measured against. These tests pin down the part that decides
whether the answer means anything: **comparable means the same KIND of thing.**
A broken iPhone is not a data point for a working one, and a replacement
display is not a data point for either — compare across those and the rule
reports a "steal" that is simply a different product.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import Listing, PriceHistory, SearchRule, SiteName, User
from app.database.models.enums import Condition
from app.services import listing_detail

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


@pytest.fixture(autouse=True)
def no_sold_comps(monkeypatch):
    """Sold comparables live in Redis; tests that want them install their own."""

    async def none(rule_id, now=None):  # noqa: ANN001
        return []

    from app.services import sold_comps

    monkeypatch.setattr(sold_comps, "realised_comps", none)


async def _tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _listing(rule_id: int, ext: str, title: str, price: float, desc: str = "") -> Listing:
    return Listing(
        rule_id=rule_id, site=SiteName.KLEINANZEIGEN, external_id=ext,
        fingerprint=f"fp-{ext}", title=title, description=desc or None,
        url=f"https://example.com/{ext}", price=price,
    )


def _run(scenario):
    async def wrapper():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=900)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="phones", keywords="iphone 14")
            session.add(rule)
            await session.flush()
            result = await scenario(session, rule)
        await db.dispose_engine()
        return result

    return asyncio.run(wrapper())


# --- The defect is visible ---------------------------------------------------------
def test_a_defect_hidden_in_the_description_is_surfaced(sqlite_db):
    async def scenario(session, rule):
        row = _listing(rule.id, "a", "iPhone 14 Pro 256GB", 400.0,
                       "Sehr guter Zustand, nur das Display ist defekt.")
        session.add(row)
        await session.commit()
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    # The title says nothing; the description is where it hides.
    assert detail.is_defective is True
    assert "defekt" in detail.defect_markers
    assert detail.text_condition is Condition.DEFECTIVE


def test_a_negated_marker_is_not_a_defect(sqlite_db):
    async def scenario(session, rule):
        row = _listing(rule.id, "a", "iPhone 14 Pro", 700.0,
                       "Voll funktionsfähig, nicht defekt, keine Kratzer.")
        session.add(row)
        await session.commit()
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    assert detail.defect_markers == []
    assert detail.is_defective is False


# --- Comparable means the same KIND -------------------------------------------------
def test_a_broken_phone_is_compared_with_broken_phones(sqlite_db):
    async def scenario(session, rule):
        broken = _listing(rule.id, "me", "iPhone 14 Pro", 300.0, "Display defekt")
        session.add(broken)
        # Three more broken ones …
        for i, price in enumerate([280.0, 320.0, 340.0]):
            session.add(_listing(rule.id, f"b{i}", "iPhone 14 Pro defekt", price))
        # … and working ones that must NOT count.
        for i, price in enumerate([800.0, 850.0, 900.0]):
            session.add(_listing(rule.id, f"w{i}", "iPhone 14 Pro", price))
        await session.commit()
        return await listing_detail.build(session, broken, now=NOW)

    detail = _run(scenario)
    assert detail.compared_with == 3          # only the broken ones
    assert detail.asking.stats.median == 320.0
    # Against working phones a 300 € broken one would look like a steal; against
    # other broken ones it is simply an ordinary price.
    assert detail.asking.discount_percent == pytest.approx(6.3, abs=0.1)


def test_a_working_phone_is_not_dragged_down_by_broken_ones(sqlite_db):
    async def scenario(session, rule):
        working = _listing(rule.id, "me", "iPhone 14 Pro", 700.0)
        session.add(working)
        for i, price in enumerate([800.0, 850.0, 900.0]):
            session.add(_listing(rule.id, f"w{i}", "iPhone 14 Pro", price))
        for i, price in enumerate([250.0, 260.0, 270.0]):
            session.add(_listing(rule.id, f"b{i}", "iPhone 14 Pro defekt", price))
        await session.commit()
        return await listing_detail.build(session, working, now=NOW)

    detail = _run(scenario)
    assert detail.compared_with == 3
    assert detail.asking.stats.median == 850.0


def test_a_spare_part_is_compared_with_spare_parts(sqlite_db):
    async def scenario(session, rule):
        part = _listing(rule.id, "me", "iPhone 14 Ersatzdisplay", 40.0)
        session.add(part)
        for i, price in enumerate([35.0, 45.0, 50.0]):
            session.add(_listing(rule.id, f"p{i}", "iPhone 14 Display Ersatzteil", price))
        for i, price in enumerate([700.0, 750.0, 800.0]):
            session.add(_listing(rule.id, f"w{i}", "iPhone 14 Pro", price))
        await session.commit()
        return await listing_detail.build(session, part, now=NOW)

    detail = _run(scenario)
    assert detail.compared_with == 3
    assert detail.asking.stats.median == 45.0


def test_too_few_comparables_is_said_not_guessed(sqlite_db):
    async def scenario(session, rule):
        row = _listing(rule.id, "me", "iPhone 14 Pro", 700.0)
        session.add(row)
        session.add(_listing(rule.id, "o", "iPhone 14 Pro", 800.0))
        await session.commit()
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    # One comparable is not a market. The number exists but is not usable.
    assert detail.compared_with == 1
    assert detail.asking.usable is False
    assert detail.best_reference is None


# --- Price history ------------------------------------------------------------------
def test_the_price_history_comes_back_oldest_first(sqlite_db):
    async def scenario(session, rule):
        row = _listing(rule.id, "me", "iPhone 14 Pro", 600.0)
        session.add(row)
        await session.flush()
        for days, price in ((3, 800.0), (2, 750.0), (1, 600.0)):
            session.add(PriceHistory(
                listing_id=row.id, price=price, observed_at=NOW - timedelta(days=days)
            ))
        await session.commit()
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    assert [p.price for p in detail.history] == [800.0, 750.0, 600.0]
    assert detail.price_fell == 200.0


def test_a_price_that_never_moved_reports_no_drop(sqlite_db):
    async def scenario(session, rule):
        row = _listing(rule.id, "me", "iPhone 14 Pro", 600.0)
        session.add(row)
        await session.flush()
        session.add(PriceHistory(listing_id=row.id, price=600.0, observed_at=NOW))
        await session.commit()
        return await listing_detail.build(session, row, now=NOW)

    assert _run(scenario).price_fell is None


def test_a_long_history_is_thinned_but_keeps_both_ends(sqlite_db):
    async def scenario(session, rule):
        row = _listing(rule.id, "me", "iPhone 14 Pro", 500.0)
        session.add(row)
        await session.flush()
        for i in range(200):
            session.add(PriceHistory(
                listing_id=row.id, price=900.0 - i,
                observed_at=NOW - timedelta(hours=200 - i),
            ))
        await session.commit()
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    assert len(detail.history) == listing_detail.MAX_HISTORY_POINTS
    # The first and the current price are the two a reader looks for.
    assert detail.history[0].price == 900.0
    assert detail.history[-1].price == 701.0


# --- Sold prices beat asking prices --------------------------------------------------
def test_what_sold_is_preferred_over_what_is_asked(sqlite_db, monkeypatch):
    from app.services import sold_comps

    async def scenario(session, rule):
        row = _listing(rule.id, "me", "iPhone 14 Pro", 600.0)
        session.add(row)
        for i, price in enumerate([900.0, 950.0, 1000.0]):
            session.add(_listing(rule.id, f"w{i}", "iPhone 14 Pro", price))
        await session.commit()

        async def realised(rule_id, now=None):  # noqa: ANN001
            # Prices of ads that are gone: retention swept the rows away.
            return [
                sold_comps.SoldComp(listing_id=9001 + n, price=price, sold_at=NOW)
                for n, price in enumerate([700.0, 720.0, 740.0])
            ]

        monkeypatch.setattr(sold_comps, "realised_comps", realised)
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    assert detail.asking.stats.median == 950.0
    assert detail.sold.stats.median == 720.0
    # Sellers hope for 950; buyers paid 720. The second is the honest reference.
    assert detail.best_reference is detail.sold
    assert detail.best_reference.discount_percent == pytest.approx(16.7, abs=0.1)


def test_without_enough_sold_prices_the_asking_ones_are_used(sqlite_db, monkeypatch):
    from app.services import sold_comps

    async def scenario(session, rule):
        row = _listing(rule.id, "me", "iPhone 14 Pro", 600.0)
        session.add(row)
        for i, price in enumerate([900.0, 950.0, 1000.0]):
            session.add(_listing(rule.id, f"w{i}", "iPhone 14 Pro", price))
        await session.commit()

        async def realised(rule_id, now=None):  # noqa: ANN001
            return [sold_comps.SoldComp(listing_id=9001, price=700.0, sold_at=NOW)]

        monkeypatch.setattr(sold_comps, "realised_comps", realised)
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    assert detail.sold.usable is False
    assert detail.best_reference is detail.asking


def test_redis_trouble_costs_the_sold_prices_not_the_page(sqlite_db, monkeypatch):
    from app.services import sold_comps

    async def scenario(session, rule):
        row = _listing(rule.id, "me", "iPhone 14 Pro", 600.0)
        session.add(row)
        for i, price in enumerate([900.0, 950.0, 1000.0]):
            session.add(_listing(rule.id, f"w{i}", "iPhone 14 Pro", price))
        await session.commit()

        async def boom(rule_id, now=None):  # noqa: ANN001
            raise ConnectionError("redis is down")

        monkeypatch.setattr(sold_comps, "realised_comps", boom)
        return await listing_detail.build(session, row, now=NOW)

    detail = _run(scenario)
    assert detail.sold is None
    assert detail.asking.usable is True  # the page still works
