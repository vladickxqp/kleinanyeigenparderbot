"""Tests for the in-bot cancellation states of the premium page."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.bot.handlers.premium import _cancellable, _premium_text
from app.database.models import SubscriptionTier, User
from app.services.premium import CANCEL_AT_PERIOD_END


def _sub(provider="telegram_stars", charge="ch_1", status="paid"):
    return SimpleNamespace(
        payment_provider=provider,
        telegram_charge_id=charge,
        payment_status=status,
        subscription_end=datetime(2026, 8, 15),
    )


def _paid_user() -> User:
    return User(telegram_id=1, subscription=SubscriptionTier.UNLIMITED)


def test_stars_subscription_is_cancellable():
    assert _cancellable(_sub()) is True


def test_non_stars_grants_are_not_cancellable():
    assert _cancellable(_sub(provider="admin_grant")) is False
    assert _cancellable(_sub(provider="trial", charge=None)) is False
    assert _cancellable(None) is False


def test_already_cancelled_is_not_cancellable_again():
    assert _cancellable(_sub(status=CANCEL_AT_PERIOD_END)) is False


def test_premium_text_shows_cancelled_state():
    text = _premium_text(_paid_user(), _sub(status=CANCEL_AT_PERIOD_END))
    assert "gekündigt" in text.lower()
    assert "15.08.2026" in text
    assert "nicht" in text  # "verlängert sich danach nicht mehr"


def test_premium_text_shows_renewal_for_active_stars_sub():
    text = _premium_text(_paid_user(), _sub())
    assert "Verlängert sich automatisch" in text


def test_premium_text_for_non_renewing_grant():
    text = _premium_text(_paid_user(), _sub(provider="admin_grant", charge=None))
    assert "läuft danach automatisch aus" in text.lower()


# --- Ending non-renewing premium (trial / grant / coupon) --------------------
def test_trial_and_grant_can_be_ended():
    from app.bot.handlers.premium import _endable

    assert _endable(_sub(provider="trial", charge=None)) is True
    assert _endable(_sub(provider="admin_grant", charge=None)) is True
    assert _endable(_sub(provider="coupon", charge=None)) is True


def test_stars_subscription_is_cancelled_not_ended():
    from app.bot.handlers.premium import _endable

    # A renewing Stars sub uses the cancel flow, never the "end" flow.
    assert _endable(_sub()) is False


def test_already_cancelled_cannot_be_ended():
    from app.bot.handlers.premium import _endable

    assert _endable(_sub(provider="trial", charge=None,
                         status=CANCEL_AT_PERIOD_END)) is False
    assert _endable(None) is False
