"""Cancelling a subscription from the Mini App.

The endpoint carries no id: it always acts on the authenticated user's own
subscription. These tests pin the two outcomes the chat already knows (stop the
Stars renewal / end a non-charging premium), the refusals, and the fact that
nobody can reach another user's subscription through it.

The outbound Telegram call is patched everywhere — no test touches the network.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routers import webapp as api
from app.database import session as db
from app.database.base import Base
from app.database.models import (
    PlanType,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)
from app.services import premium

TABLES = ["users", "search_rules", "listings", "subscriptions", "payments"]


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


@pytest.fixture()
def telegram_calls(monkeypatch):
    """Record cancellations instead of calling api.telegram.org."""
    calls: list[tuple[int, str]] = []

    async def fake_cancel(telegram_id: int, charge_id: str) -> bool:
        calls.append((telegram_id, charge_id))
        return True

    monkeypatch.setattr(premium, "cancel_stars_subscription", fake_cancel)
    return calls


async def _create_tables() -> None:
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Base.metadata.tables[name] for name in TABLES],
        )


END = datetime(2026, 12, 24, 12, 0, tzinfo=timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    """SQLite hands timestamps back without a zone — compare them in UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _premium_user(
    session,
    telegram_id: int,
    *,
    provider: str = "telegram_stars",
    charge_id: str | None = "ch_1",
    plan: PlanType = PlanType.MONTHLY,
    end: datetime = END,
) -> tuple[User, Subscription]:
    """A user with one ACTIVE subscription of the given kind."""
    user = User(telegram_id=telegram_id, subscription=SubscriptionTier.UNLIMITED)
    session.add(user)
    await session.flush()
    sub = Subscription(
        user_id=user.id,
        telegram_id=telegram_id,
        status=SubscriptionStatus.ACTIVE,
        plan_type=plan,
        subscription_start=end - timedelta(days=30),
        subscription_end=end,
        renewal_date=end,
        payment_provider=provider,
        payment_status="paid" if provider == "telegram_stars" else "granted",
        telegram_charge_id=charge_id,
        tier=SubscriptionTier.UNLIMITED.value,
    )
    session.add(sub)
    await session.flush()
    return user, sub


def test_cancelling_a_stars_subscription_keeps_the_paid_period(sqlite_db, telegram_calls):
    """The renewal stops at Telegram; the already-paid period stays untouched."""

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            user, sub = await _premium_user(session, 1)

            result = await api.cancel_subscription(user=user, session=session)

            assert result.outcome == premium.CANCEL_AT_PERIOD_END
            assert _utc(result.active_until) == END
            assert result.is_paid is True          # premium keeps running
            assert result.renews is False
            assert "24.12.2026" in result.detail

            # Telegram was asked exactly once, for this user's own charge.
            assert telegram_calls == [(1, "ch_1")]

            await session.refresh(sub)
            assert sub.payment_status == premium.CANCEL_AT_PERIOD_END
            assert _utc(sub.subscription_end) == END   # end date intact
            assert sub.renewal_date is None
            assert sub.status is SubscriptionStatus.ACTIVE
            assert user.subscription is SubscriptionTier.UNLIMITED
        await db.dispose_engine()

    asyncio.run(scenario())


def test_cancelling_a_granted_premium_ends_it(sqlite_db, telegram_calls):
    """Nothing is charged for a gift, so it is handed back immediately."""

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            user, sub = await _premium_user(
                session, 2, provider="admin_grant", charge_id=None,
                plan=PlanType.ADMIN_GRANT,
            )

            result = await api.cancel_subscription(user=user, session=session)

            assert result.outcome == "ended"
            assert result.active_until is None
            assert result.is_paid is False
            assert result.tier == SubscriptionTier.FREE.value
            assert telegram_calls == []              # no Stars renewal involved

            await session.refresh(sub)
            assert sub.status is SubscriptionStatus.CANCELED
            assert user.subscription is SubscriptionTier.FREE
        await db.dispose_engine()

    asyncio.run(scenario())


def test_cancelling_a_trial_ends_it(sqlite_db, telegram_calls):
    """A trial is the same case as a gift: no charge, so it ends now."""

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            user, sub = await _premium_user(
                session, 3, provider="trial", charge_id=None, plan=PlanType.TRIAL,
            )

            result = await api.cancel_subscription(user=user, session=session)

            assert result.outcome == "ended"
            assert result.is_paid is False
            assert telegram_calls == []
            await session.refresh(sub)
            assert sub.status is SubscriptionStatus.CANCELED
        await db.dispose_engine()

    asyncio.run(scenario())


def test_cancelling_twice_changes_nothing(sqlite_db, telegram_calls):
    """A double tap must not charge Telegram again or move the end date."""

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            user, sub = await _premium_user(session, 4)
            await api.cancel_subscription(user=user, session=session)

            with pytest.raises(HTTPException) as exc:
                await api.cancel_subscription(user=user, session=session)
            assert exc.value.status_code == 409

            assert telegram_calls == [(4, "ch_1")]   # exactly once
            await session.refresh(sub)
            assert sub.payment_status == premium.CANCEL_AT_PERIOD_END
            assert _utc(sub.subscription_end) == END
            assert user.subscription is SubscriptionTier.UNLIMITED
        await db.dispose_engine()

    asyncio.run(scenario())


def test_ending_a_grant_twice_changes_nothing(sqlite_db, telegram_calls):
    """Same for the "end now" case: the second call finds nothing active."""

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            user, _ = await _premium_user(
                session, 5, provider="coupon", charge_id=None, plan=PlanType.COUPON,
            )
            await api.cancel_subscription(user=user, session=session)

            with pytest.raises(HTTPException) as exc:
                await api.cancel_subscription(user=user, session=session)
            assert exc.value.status_code == 409
            assert user.subscription is SubscriptionTier.FREE
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_user_cannot_cancel_someone_elses_subscription(sqlite_db, telegram_calls):
    """The endpoint takes no id — it only ever sees the caller's own row."""

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            victim, victim_sub = await _premium_user(session, 10)
            attacker = User(telegram_id=11)
            session.add(attacker)
            await session.flush()

            with pytest.raises(HTTPException) as exc:
                await api.cancel_subscription(user=attacker, session=session)
            assert exc.value.status_code == 409

            assert telegram_calls == []
            await session.refresh(victim_sub)
            assert victim_sub.payment_status == "paid"
            assert _utc(victim_sub.renewal_date) == END
            assert victim_sub.status is SubscriptionStatus.ACTIVE
            assert victim.subscription is SubscriptionTier.UNLIMITED
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_user_without_premium_gets_a_clean_refusal(sqlite_db, telegram_calls):
    """No subscription at all: a 409 with a sentence, not a crash."""

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=12)
            session.add(user)
            await session.flush()

            with pytest.raises(HTTPException) as exc:
                await api.cancel_subscription(user=user, session=session)
            assert exc.value.status_code == 409
            assert "gekündigt" in exc.value.detail
            assert telegram_calls == []
        await db.dispose_engine()

    asyncio.run(scenario())


def test_a_failed_telegram_call_leaves_the_subscription_alone(sqlite_db, monkeypatch):
    """If Telegram refuses, the row must not claim the renewal is stopped."""

    async def fake_cancel(telegram_id: int, charge_id: str) -> bool:
        return False

    monkeypatch.setattr(premium, "cancel_stars_subscription", fake_cancel)

    async def scenario() -> None:
        await _create_tables()
        async with db.get_sessionmaker()() as session:
            user, sub = await _premium_user(session, 13)

            with pytest.raises(HTTPException) as exc:
                await api.cancel_subscription(user=user, session=session)
            assert exc.value.status_code == 502

            await session.refresh(sub)
            assert sub.payment_status == "paid"
            assert _utc(sub.renewal_date) == END
        await db.dispose_engine()

    asyncio.run(scenario())


# --- The app must judge a subscription exactly like the chat does ------------
def _sub(provider="telegram_stars", charge="ch_1", status="paid"):
    return SimpleNamespace(
        payment_provider=provider,
        telegram_charge_id=charge,
        payment_status=status,
        subscription_end=END,
    )


def test_the_app_and_the_bot_agree_on_what_can_be_cancelled():
    """Two implementations, one rule: drift here would confuse every user."""
    from app.bot.handlers import premium as bot

    cases = [
        None,
        _sub(),
        _sub(status=premium.CANCEL_AT_PERIOD_END),
        _sub(provider="admin_grant", charge=None),
        _sub(provider="trial", charge=None),
        _sub(provider="coupon", charge=None),
        _sub(provider="telegram_stars", charge=None),
        _sub(provider="trial", charge=None, status=premium.CANCEL_AT_PERIOD_END),
    ]
    for case in cases:
        assert api._cancellable(case) is bot._cancellable(case)
        assert api._endable(case) is bot._endable(case)


def test_cancel_kind_names_the_action_the_account_tab_offers():
    assert api._cancel_kind(_sub()) == api.CANCEL_RENEWAL
    assert api._cancel_kind(_sub(provider="trial", charge=None)) == api.CANCEL_PREMIUM
    assert api._cancel_kind(_sub(status=premium.CANCEL_AT_PERIOD_END)) is None
    assert api._cancel_kind(None) is None
