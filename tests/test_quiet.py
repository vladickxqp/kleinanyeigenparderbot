"""Tests for the quiet-hours window logic (pure part, no Redis)."""

from __future__ import annotations

from app.services.quiet import DIGEST_MAX_CARDS, is_in_window


def test_window_wrapping_midnight():
    # Classic night window 22:00 -> 07:00
    assert is_in_window(23, 22, 7) is True
    assert is_in_window(0, 22, 7) is True
    assert is_in_window(6, 22, 7) is True
    assert is_in_window(7, 22, 7) is False   # end is exclusive
    assert is_in_window(12, 22, 7) is False
    assert is_in_window(21, 22, 7) is False
    assert is_in_window(22, 22, 7) is True   # start is inclusive


def test_window_same_day():
    assert is_in_window(10, 9, 17) is True
    assert is_in_window(8, 9, 17) is False
    assert is_in_window(17, 9, 17) is False


def test_zero_length_window_is_disabled():
    assert is_in_window(5, 5, 5) is False


def test_digest_cap_is_reasonable():
    assert 1 <= DIGEST_MAX_CARDS <= 20
