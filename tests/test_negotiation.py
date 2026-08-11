"""Tests for the negotiation assistant's offer suggestions."""

from __future__ import annotations

from app.services.negotiation import build_message, suggest_offer


def test_offers_are_below_asking_and_nicely_rounded():
    assert suggest_offer(500, discount_percent=12) == 440
    assert suggest_offer(1300, discount_percent=12) == 1150
    assert suggest_offer(27900, discount_percent=12) == 24600
    assert suggest_offer(45, discount_percent=12) == 40


def test_offer_never_reaches_asking_price():
    for price in (10, 55, 99, 250, 999, 12345):
        assert suggest_offer(price, discount_percent=1) < price


def test_offer_is_at_least_one_euro():
    assert suggest_offer(2, discount_percent=90) >= 1


def test_message_contains_offer_and_title():
    msg = build_message("Tesla Model 3 Long Range", 27900, 24600)
    assert "24600" in msg
    assert "Tesla Model 3" in msg
    assert "Grüße" in msg
