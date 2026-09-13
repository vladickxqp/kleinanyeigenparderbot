"""Tests for the user-facing payment history, billing dates and refunds."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.database import session as db
from app.database.base import Base
from app.database.models import SubscriptionTier, User
from app.services import premium


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


def test_history_billing_and_refund(sqlite_db):
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
            user = User(telegram_id=77, subscription=SubscriptionTier.FREE)
            session.add(user)
            await session.flush()

            # Nothing yet: empty history, no dates.
            info = await premium.billing_info(session, 77)
            assert info.payments_count == 0 and info.last_charge_at is None
            assert await premium.payment_history(session, 77) == []

            # An admin gift (never a charge), then a purchase, then a renewal.
            await premium.record_payment(
                session, user, provider="admin_grant", amount_stars=0, status="granted"
            )
            first = await premium.record_payment(
                session, user, provider="telegram_stars", amount_stars=250,
                amount_eur=4.99, charge_id="ch_1",
            )
            renewal = await premium.record_payment(
                session, user, provider="telegram_stars", amount_stars=250,
                amount_eur=4.99, charge_id="ch_2", is_renewal=True,
            )

            # Newest first (id breaks same-second timestamp ties).
            history = await premium.payment_history(session, 77)
            assert [p.charge_id for p in history] == ["ch_2", "ch_1", None]

            info = await premium.billing_info(session, 77)
            assert info.payments_count == 2
            assert info.last_amount_stars == 250
            assert info.last_charge_at is not None
            # Telegram charges every 30 days: next = last + 30d.
            assert info.next_charge_at == info.last_charge_at + timedelta(days=30)

            # Refund of the last charge is recorded and visible in the history.
            refunded = await premium.mark_refunded(session, 77, "ch_2")
            assert refunded is not None and refunded.id == renewal.id
            assert refunded.refunded is True and refunded.status == "refunded"
            assert first.refunded is False
            assert await premium.mark_refunded(session, 77, "does-not-exist") is None
        await db.dispose_engine()

    asyncio.run(scenario())
