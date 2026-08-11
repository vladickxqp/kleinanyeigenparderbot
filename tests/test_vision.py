"""Tests for the photo-assessment JSON parsing and access gate."""

from __future__ import annotations

from app.bot.handlers.photo_eval import _may_use_photo_eval
from app.config.settings import settings
from app.database.models import SubscriptionTier, User
from app.services.vision import _parse_response


# --- JSON parsing -----------------------------------------------------------------
def test_parse_valid_assessment():
    raw = (
        '{"product": "Nvidia RTX 4090 Founders Edition", '
        '"search_query": "rtx 4090 founders", "est_value_eur": 950, '
        '"confidence": "high", "notes": "Auf Lüfter achten."}'
    )
    result = _parse_response(raw)
    assert result is not None
    assert result.product.startswith("Nvidia RTX 4090")
    assert result.est_value_eur == 950.0
    assert result.confidence == "high"


def test_parse_tolerates_code_fences_and_null_value():
    raw = (
        '```json\n{"product": "iPhone 17 Pro", "search_query": "iphone 17 pro",'
        ' "est_value_eur": null, "confidence": "medium", "notes": ""}\n```'
    )
    result = _parse_response(raw)
    assert result is not None
    assert result.est_value_eur is None


def test_parse_rejects_garbage_and_missing_fields():
    assert _parse_response("kein json") is None
    assert _parse_response('{"product": "", "search_query": ""}') is None


def test_parse_normalises_bad_confidence():
    raw = (
        '{"product": "PS5", "search_query": "playstation 5", '
        '"est_value_eur": 300, "confidence": "very sure!!", "notes": ""}'
    )
    result = _parse_response(raw)
    assert result is not None
    assert result.confidence == "low"


# --- Access gate ------------------------------------------------------------------
def test_photo_eval_gate(monkeypatch):
    monkeypatch.setattr(settings, "photo_ai_premium_only", True)
    monkeypatch.setattr(settings, "bot_admin_ids", "999")

    free_user = User(telegram_id=1, subscription=SubscriptionTier.FREE)
    paid_user = User(telegram_id=2, subscription=SubscriptionTier.UNLIMITED)
    admin = User(telegram_id=999, subscription=SubscriptionTier.FREE)

    assert _may_use_photo_eval(free_user) is False
    assert _may_use_photo_eval(paid_user) is True
    assert _may_use_photo_eval(admin) is True

    # With the premium gate disabled, everyone may use it.
    monkeypatch.setattr(settings, "photo_ai_premium_only", False)
    assert _may_use_photo_eval(free_user) is True
