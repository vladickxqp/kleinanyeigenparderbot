"""Tests for price statistics and anomaly detection."""

from __future__ import annotations

from app.services.price_analysis import compute_price_stats


def test_empty_prices_have_no_data():
    stats = compute_price_stats([])
    assert stats.count == 0
    assert not stats.has_data
    assert stats.discount_percent(100) is None


def test_basic_statistics():
    stats = compute_price_stats([100, 200, 300])
    assert stats.count == 3
    assert stats.minimum == 100
    assert stats.maximum == 300
    assert stats.average == 200
    assert stats.median == 200


def test_ignores_non_positive_values():
    stats = compute_price_stats([0, -5, 50, 150])
    assert stats.count == 2
    assert stats.minimum == 50


def test_discount_percent_relative_to_median():
    stats = compute_price_stats([100, 100, 100, 100])
    # Half the median price -> 50% discount.
    assert stats.discount_percent(50) == 50.0


def test_anomaly_detection_flags_low_outlier():
    prices = [1000, 1020, 980, 1010, 990, 1005]
    stats = compute_price_stats(prices)
    assert stats.is_anomaly(400) is True
    assert stats.is_anomaly(995) is False
