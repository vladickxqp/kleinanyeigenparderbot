"""Tests for subscription tiers, interval floor and HTML-safe rendering."""

from __future__ import annotations

from app.database.models import User
from app.database.models.enums import SubscriptionTier


# --- Tiers ----------------------------------------------------------------------
def _user(tier: SubscriptionTier) -> User:
    return User(telegram_id=1, subscription=tier)


def test_tier_quotas():
    from app.config.settings import settings

    assert _user(SubscriptionTier.FREE).max_rules == settings.free_max_rules
    assert _user(SubscriptionTier.STARTER).max_rules == settings.starter_max_rules
    assert _user(SubscriptionTier.PRO).max_rules == settings.pro_max_rules
    assert _user(SubscriptionTier.UNLIMITED).max_rules == settings.dealer_max_rules
    # Real numbers only — a sentinel would break the reconciliation math.
    assert _user(SubscriptionTier.UNLIMITED).max_rules < 10_000


def test_legacy_tiers_still_load_and_map():
    # Rows written by old versions must keep working.
    assert SubscriptionTier("premium") is SubscriptionTier.PREMIUM
    assert SubscriptionTier("ultimate") is SubscriptionTier.ULTIMATE
    assert _user(SubscriptionTier.PREMIUM).max_rules == _user(SubscriptionTier.PRO).max_rules
    assert _user(SubscriptionTier.ULTIMATE).max_rules == _user(SubscriptionTier.UNLIMITED).max_rules
    assert SubscriptionTier.PREMIUM.canonical is SubscriptionTier.PRO
    assert SubscriptionTier.ULTIMATE.rank == SubscriptionTier.UNLIMITED.rank


def test_settier_offers_only_current_tiers():
    from app.bot.handlers.admin import ASSIGNABLE_TIERS

    assert {"free", "starter", "pro", "dealer"} <= set(ASSIGNABLE_TIERS)
    assert "premium" not in ASSIGNABLE_TIERS and "ultimate" not in ASSIGNABLE_TIERS


# --- Interval floor ---------------------------------------------------------------
def test_interval_choices_have_one_minute_floor():
    from app.bot.keyboards import INTERVAL_CHOICES

    assert all(seconds >= 60 for seconds, _ in INTERVAL_CHOICES)
    from app.config.settings import settings

    assert settings.scraper_hard_min_interval_seconds == 60


# --- HTML-safe rendering ------------------------------------------------------------
def test_render_rule_escapes_user_content():
    from app.bot.handlers.rules import _render_rule
    from app.database.models import SearchRule

    rule = SearchRule(
        user_id=1,
        name="RTX <3000 & Co",
        keywords="rtx <b>4090</b>",
        exclude_keywords=["<defekt>"],
        location="Worms <Innenstadt>",
        max_distance_km=50,
        sites=[],
        interval_seconds=300,
        min_deal_score=0,
        is_active=True,
    )
    text = _render_rule(rule)
    assert "<3000" not in text and "&lt;3000" in text
    assert "<b>4090</b>" not in text and "&lt;b&gt;4090&lt;/b&gt;" in text
    assert "<defekt>" not in text
    assert "<Innenstadt>" not in text
