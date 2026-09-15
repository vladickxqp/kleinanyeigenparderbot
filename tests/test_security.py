"""Security regressions: ownership scoping, tier enforcement, payment replay.

Every case here was a real hole found during the September audit, so each test
fails loudly if the protection is ever removed again.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import (
    Listing,
    SearchRule,
    SiteName,
    SubscriptionTier,
    User,
)
from app.services.premium import charge_already_processed, enforce_tier_limits
from app.services.repositories import ListingRepository, SearchRuleRepository

TABLES = ["users", "search_rules", "listings", "subscriptions", "payments"]


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


def _listing(rule_id: int, ext: str) -> Listing:
    return Listing(
        rule_id=rule_id,
        site=SiteName.KLEINANZEIGEN,
        external_id=ext,
        fingerprint=f"fp-{ext}",
        title=f"Item {ext}",
        url=f"https://example.com/{ext}",
    )


def test_rule_and_listing_lookups_are_owner_scoped(sqlite_db):
    """Callback data is client-controlled: ids alone must grant nothing."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            owner = User(telegram_id=1)
            attacker = User(telegram_id=2)
            session.add_all([owner, attacker])
            await session.flush()

            rule = SearchRule(user_id=owner.id, name="Mine", keywords="tesla")
            session.add(rule)
            await session.flush()
            listing = _listing(rule.id, "a1")
            session.add(listing)
            await session.flush()

            rules = SearchRuleRepository(session)
            listings = ListingRepository(session)

            assert await rules.get(rule.id, owner.id) is not None
            assert await rules.get(rule.id, attacker.id) is None
            # System code (worker) may still look a rule up without an owner.
            assert await rules.get_unscoped(rule.id) is not None

            assert await listings.get_for_user(listing.id, owner.id) is not None
            assert await listings.get_for_user(listing.id, attacker.id) is None
        await db.dispose_engine()

    asyncio.run(scenario())


def test_downgrade_reconciles_rules_to_the_free_tier(sqlite_db):
    """A lapsed subscriber must not keep premium quotas and intervals."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            user = User(telegram_id=7, subscription=SubscriptionTier.UNLIMITED)
            session.add(user)
            await session.flush()

            for i in range(6):
                session.add(
                    SearchRule(
                        user_id=user.id, name=f"r{i}", keywords=f"kw{i}",
                        interval_seconds=60,
                    )
                )
            await session.flush()

            # Still premium: nothing to reconcile.
            assert await enforce_tier_limits(session, user) == (0, 0)

            user.subscription = SubscriptionTier.FREE
            await session.flush()
            paused, slowed = await enforce_tier_limits(session, user)

            assert paused == 6 - user.max_rules
            assert slowed == 6
            active = [
                r for r in (await SearchRuleRepository(session).list_for_user(user.id))
                if r.is_active
            ]
            assert len(active) == user.max_rules
            assert all(r.interval_seconds >= user.min_interval_seconds for r in active)
        await db.dispose_engine()

    asyncio.run(scenario())


def test_duplicate_charge_is_detected(sqlite_db):
    """A redelivered successful_payment must not be booked twice."""

    async def scenario() -> None:
        await _create_tables()
        maker = db.get_sessionmaker()
        async with maker() as session:
            from app.services.premium import record_payment

            user = User(telegram_id=9)
            session.add(user)
            await session.flush()

            assert await charge_already_processed(session, "ch_x") is False
            await record_payment(
                session, user, provider="telegram_stars", charge_id="ch_x",
                amount_stars=250,
            )
            assert await charge_already_processed(session, "ch_x") is True
            assert await charge_already_processed(session, "") is False
        await db.dispose_engine()

    asyncio.run(scenario())


def test_placeholder_secrets_are_reported():
    """Shipping the repository's default JWT secret must be detectable."""
    from app.config.settings import Settings

    insecure = Settings(
        jwt_secret_key="change_me_generate_a_long_random_secret",
        postgres_password="change_me_postgres",
        environment="production",
    )
    assert set(insecure.insecure_secrets()) == {"JWT_SECRET_KEY", "POSTGRES_PASSWORD"}
    with pytest.raises(RuntimeError):
        insecure.require_secure_secrets()

    secure = Settings(
        jwt_secret_key="x" * 48,
        postgres_password="a-real-generated-password",
        environment="production",
    )
    assert secure.insecure_secrets() == []
    secure.require_secure_secrets()


def test_deal_card_escapes_a_hostile_url():
    """Scraped URLs end up in an HTML attribute and must be escaped."""
    from app.bot.formatting import format_deal_card

    listing = _listing(1, "x")
    listing.url = 'https://evil.test/"><b>pwn</b><a href="'
    listing.price = 100.0
    listing.currency = "EUR"
    listing.deal_score = 50

    card = format_deal_card(listing)
    assert "<b>pwn</b>" not in card
    assert "&quot;&gt;&lt;b&gt;pwn" in card
