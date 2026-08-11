"""Tests for the fee-aware flip-profit estimate."""

from __future__ import annotations

from app.bot.formatting import net_flip_profit
from app.config.settings import settings


def test_net_profit_subtracts_fees_and_shipping(monkeypatch):
    monkeypatch.setattr(settings, "resale_fee_percent", 10.0)
    monkeypatch.setattr(settings, "resale_shipping_eur", 5.0)
    # market 1000 -> proceeds 900, minus shipping 5, minus purchase 500 = 395
    assert net_flip_profit(500.0, 1000.0) == 395.0


def test_gross_profit_can_be_net_loss(monkeypatch):
    monkeypatch.setattr(settings, "resale_fee_percent", 13.0)
    monkeypatch.setattr(settings, "resale_shipping_eur", 5.90)
    # Gross +50 looks tempting; net is negative after 13% fees on 850.
    assert net_flip_profit(800.0, 850.0) < 0
