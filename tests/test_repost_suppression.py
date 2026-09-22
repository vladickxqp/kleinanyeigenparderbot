"""The same offer under a new ad id is not a new find.

Deleting an ad and posting it again is how people push themselves back to the
top of a Kleinanzeigen result list, and the fresh ad id makes it look brand
new to the bot: site + id is the identity, and a repost has neither. So the
user was told about the same thing again — and again — each card spending one
of their daily quota.

``repost_fingerprint`` was written for exactly this and then wired to nothing.
These tests pin down what it does now, and just as importantly what it must
NOT do: it decides what gets DELIVERED twice, never what gets STORED. Two
sellers really can offer "PS5 Controller" at 25 €, which is why identity stayed
on the ad id.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config.settings import settings
from app.database import session as db
from app.database.base import Base
from app.database.models import Listing, SearchRule, SiteName, User
from app.parsers.schemas import ParsedListing
from app.services.dedup import repost_key
from app.services.repositories import ListingRepository

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


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


def _parsed(ext: str, title: str, price: float) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN, external_id=ext, title=title,
        url=f"https://example.com/{ext}", price=price,
    )


# --- The key itself ----------------------------------------------------------------
def test_a_repost_shares_the_key_but_not_the_identity():
    first = _parsed("1001", "PS5 Slim OVP", 380.0)
    again = _parsed("2002", "PS5 Slim  OVP!", 380.0)   # deleted and re-posted
    assert first.repost_fingerprint == again.repost_fingerprint
    # Identity stays the ad id, so both are still stored as separate rows.
    assert first.fingerprint != again.fingerprint


def test_a_different_price_is_a_different_offer():
    assert (
        _parsed("1", "PS5 Slim OVP", 380.0).repost_fingerprint
        != _parsed("2", "PS5 Slim OVP", 300.0).repost_fingerprint
    )


def test_a_different_item_is_a_different_offer():
    assert (
        _parsed("1", "PS5 Slim OVP", 380.0).repost_fingerprint
        != _parsed("2", "PS5 Pro OVP", 380.0).repost_fingerprint
    )


def test_the_parsed_listing_and_the_stored_row_are_keyed_the_same_way():
    """Two definitions would mean suppression silently matches nothing."""
    item = _parsed("1", "PS5 Slim OVP", 380.0)
    assert item.repost_fingerprint == repost_key(
        SiteName.KLEINANZEIGEN, "PS5 Slim OVP", 380.0
    )


# --- What the repository reports ----------------------------------------------------
def _stored(rule_id: int, ext: str, title: str, price: float, *, notified: bool,
            age_days: float = 0) -> Listing:
    return Listing(
        rule_id=rule_id, site=SiteName.KLEINANZEIGEN, external_id=ext,
        fingerprint=f"fp-{ext}", title=title, url=f"https://example.com/{ext}",
        price=price, notified=notified, created_at=NOW - timedelta(days=age_days),
    )


def _with_rule(scenario):
    async def wrapper():
        await _tables()
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=800)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="ps5", keywords="ps5")
            session.add(rule)
            await session.flush()
            result = await scenario(session, rule)
        await db.dispose_engine()
        return result

    return asyncio.run(wrapper())


def test_only_delivered_offers_block_a_repost(sqlite_db):
    async def scenario(session, rule):
        session.add(_stored(rule.id, "a", "PS5 Slim OVP", 380.0, notified=True))
        # Never delivered: it cannot be the reason to stay silent now.
        session.add(_stored(rule.id, "b", "Xbox Series X", 300.0, notified=False))
        await session.commit()
        return await ListingRepository(session).recent_repost_keys(
            rule.id, NOW - timedelta(days=14)
        )

    keys = _with_rule(scenario)
    assert repost_key(SiteName.KLEINANZEIGEN, "PS5 Slim OVP", 380.0) in keys
    assert repost_key(SiteName.KLEINANZEIGEN, "Xbox Series X", 300.0) not in keys


def test_an_old_delivery_stops_blocking(sqlite_db):
    """Beyond the window the same title and price is plausibly someone else."""

    async def scenario(session, rule):
        session.add(_stored(rule.id, "a", "PS5 Slim OVP", 380.0, notified=True,
                            age_days=40))
        await session.commit()
        return await ListingRepository(session).recent_repost_keys(
            rule.id, NOW - timedelta(days=14)
        )

    assert _with_rule(scenario) == set()


def test_another_rule_s_deliveries_do_not_leak_in(sqlite_db):
    async def scenario(session, rule):
        other = SearchRule(user_id=rule.user_id, name="xbox", keywords="xbox")
        session.add(other)
        await session.flush()
        session.add(_stored(other.id, "a", "PS5 Slim OVP", 380.0, notified=True))
        await session.commit()
        return await ListingRepository(session).recent_repost_keys(
            rule.id, NOW - timedelta(days=14)
        )

    # Cross-rule duplicates are a separate mechanism with its own semantics.
    assert _with_rule(scenario) == set()


# --- The switch ---------------------------------------------------------------------
def test_the_window_and_the_switch_are_configurable(monkeypatch):
    monkeypatch.setattr(settings, "repost_window_days", 3)
    monkeypatch.setattr(settings, "repost_suppression_enabled", False)
    assert settings.repost_window_days == 3
    assert settings.repost_suppression_enabled is False


def test_the_pipeline_asks_before_it_delivers():
    """Wired, not merely written — the property spent months connected to nothing."""
    import inspect

    from app.services import search_service

    source = inspect.getsource(search_service.SearchService.run_rule)
    assert "recent_repost_keys" in source
    assert "repost_suppression_enabled" in source
