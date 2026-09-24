"""The market report a Profi rule was sold with.

The tier comparison has listed "Marktbericht" for months; nothing produced
one. These tests pin down what it says, that it says it in every language,
and that it tells the truth where the truth is "not enough data yet".
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.bot.keyboards import rule_actions_keyboard
from app.bot.texts import SUPPORTED_LANGUAGES
from app.config.settings import settings
from app.database import session as db
from app.database.base import Base
from app.database.models import Listing, SearchRule, SiteName, SubscriptionTier, User
from app.database.models.enums import DealVerdict
from app.services import entitlements as ent
from app.services import market_report, sold_comps
from app.services.price_analysis import compute_price_stats

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def sqlite_db(monkeypatch):
    monkeypatch.setattr(db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://"))
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


@pytest.fixture()
def no_sales(monkeypatch):
    async def empty(rule_id, *, now=None):  # noqa: ANN001
        return compute_price_stats([])

    monkeypatch.setattr(sold_comps, "realised_stats", empty)


def _row(rule_id: int, ext: str, price: float, *, age_days: float, score: int = 50,
         site: SiteName = SiteName.KLEINANZEIGEN, ignored: bool = False) -> Listing:
    return Listing(
        rule_id=rule_id, site=site, external_id=ext, fingerprint=f"fp-{ext}",
        title=f"PS5 {ext}", url=f"https://example.com/{ext}", price=price,
        deal_score=score, deal_verdict=DealVerdict.GOOD if score >= 70 else DealVerdict.FAIR,
        is_ignored=ignored, created_at=NOW - timedelta(days=age_days),
    )


def _build(rows_factory):
    async def scenario():
        engine = db.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.get_sessionmaker()() as session:
            user = User(telegram_id=900)
            session.add(user)
            await session.flush()
            rule = SearchRule(user_id=user.id, name="PS5 <300", keywords="ps5")
            session.add(rule)
            await session.flush()
            for row in rows_factory(rule.id):
                session.add(row)
            await session.commit()
            report = await market_report.build(session, rule, now=NOW)
        await db.dispose_engine()
        return report

    return asyncio.run(scenario())


# --- What the report contains -------------------------------------------------------
def test_the_window_and_the_one_before_it_are_kept_apart(sqlite_db, no_sales):
    report = _build(lambda rid: [
        _row(rid, "a", 400.0, age_days=1),
        _row(rid, "b", 500.0, age_days=10),
        _row(rid, "c", 600.0, age_days=29),
        # The month before: dearer. Must not leak into "found".
        _row(rid, "d", 550.0, age_days=35),
        _row(rid, "e", 500.0, age_days=50),
        # Older than both windows: invisible.
        _row(rid, "f", 900.0, age_days=70),
    ])
    assert report.found == 3
    assert report.asking.median == 500.0
    assert report.previous.median == 525.0
    assert report.trend_percent == pytest.approx(-4.8, abs=0.1)


def test_no_earlier_period_means_no_trend(sqlite_db, no_sales):
    report = _build(lambda rid: [_row(rid, "a", 400.0, age_days=1)])
    assert report.trend_percent is None
    assert "Vergleichszeitraum" in market_report.render(report, "de")


def test_the_best_finds_come_first_and_ignored_ones_not_at_all(sqlite_db, no_sales):
    report = _build(lambda rid: [
        _row(rid, "meh", 500.0, age_days=1, score=40),
        _row(rid, "top", 300.0, age_days=2, score=95),
        _row(rid, "good", 400.0, age_days=3, score=75),
        _row(rid, "hidden", 250.0, age_days=1, score=99, ignored=True),
        _row(rid, "also", 450.0, age_days=4, score=60),
    ])
    assert [r.external_id for r in report.top] == ["top", "good", "also"]


def test_finds_are_counted_per_marketplace(sqlite_db, no_sales):
    report = _build(lambda rid: [
        _row(rid, "a", 400.0, age_days=1),
        _row(rid, "b", 410.0, age_days=1, site=SiteName.EBAY),
        _row(rid, "c", 420.0, age_days=1),
    ])
    assert report.by_site[0] == ("Kleinanzeigen", 2)
    assert report.by_site[1][1] == 1


# --- How it is worded ---------------------------------------------------------------
@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_it_renders_in_every_language_without_a_loose_placeholder(sqlite_db, no_sales, lang):
    report = _build(lambda rid: [
        _row(rid, "a", 400.0, age_days=1, score=90),
        _row(rid, "b", 500.0, age_days=10),
        _row(rid, "c", 560.0, age_days=40),
    ])
    text = market_report.render(report, lang)
    assert "PS5 &lt;300" in text          # the rule name, HTML-escaped
    assert "{" not in text and "}" not in text
    assert "https://example.com/a" in text


def test_an_empty_window_says_so_instead_of_reporting_nothing(sqlite_db, no_sales):
    report = _build(lambda rid: [_row(rid, "old", 400.0, age_days=45)])
    text = market_report.render(report, "en")
    assert "No finds in the last 30 days" in text


def test_a_small_move_is_stable_not_a_trend(sqlite_db, no_sales):
    report = _build(lambda rid: [
        _row(rid, "a", 500.0, age_days=1),
        _row(rid, "b", 510.0, age_days=40),   # 2 % — inside the flat band
    ])
    assert "stabil" in market_report.render(report, "de")


def test_a_real_move_is_named_with_its_direction(sqlite_db, no_sales):
    up = _build(lambda rid: [
        _row(rid, "a", 600.0, age_days=1),
        _row(rid, "b", 500.0, age_days=40),
    ])
    assert "📈" in market_report.render(up, "de") and "+20 %" in market_report.render(up, "de")


def test_sold_prices_need_the_same_sample_as_a_verdict(sqlite_db, monkeypatch):
    monkeypatch.setattr(settings, "min_confident_comparables", 5)

    async def thin(rule_id, *, now=None):  # noqa: ANN001
        return compute_price_stats([450.0, 470.0])

    monkeypatch.setattr(sold_comps, "realised_stats", thin)
    report = _build(lambda rid: [_row(rid, "a", 500.0, age_days=1)])
    assert "zu wenige" in market_report.render(report, "de")

    async def enough(rule_id, *, now=None):  # noqa: ANN001
        return compute_price_stats([450.0, 460.0, 470.0, 480.0, 490.0])

    monkeypatch.setattr(sold_comps, "realised_stats", enough)
    report = _build(lambda rid: [_row(rid, "a", 500.0, age_days=1)])
    text = market_report.render(report, "de")
    assert "Tatsächlich verkauft" in text and "470 €" in text


def test_a_broken_sales_store_does_not_break_the_report(sqlite_db, monkeypatch):
    async def boom(rule_id, *, now=None):  # noqa: ANN001
        raise ConnectionError("redis down")

    monkeypatch.setattr(sold_comps, "realised_stats", boom)
    report = _build(lambda rid: [_row(rid, "a", 500.0, age_days=1)])
    assert report.sold.has_data is False
    assert "Marktbericht" in market_report.render(report, "de")


# --- Where it is offered, and to whom -----------------------------------------------
def test_the_rule_page_offers_report_and_export():
    rule = SimpleNamespace(id=7, is_active=True, name="x")
    markup = rule_actions_keyboard(rule, "de")
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "rule:report:7" in data
    assert "rule:export:7" in data


def test_the_features_are_unlocked_by_the_levels_they_were_sold_with(monkeypatch):
    monkeypatch.setattr(settings, "free_features", "")
    monkeypatch.setattr(settings, "starter_features", "flip_mode")
    monkeypatch.setattr(settings, "pro_features", "flip_mode,rule_power,export,market_report")
    monkeypatch.setattr(settings, "dealer_features", "flip_mode,rule_power,export,market_report,forwarding")
    assert ent.unlocks(ent.FEATURE_MARKET_REPORT) is SubscriptionTier.PRO
    assert ent.unlocks(ent.FEATURE_EXPORT) is SubscriptionTier.PRO
    assert ent.unlocks(ent.FEATURE_FORWARDING) is SubscriptionTier.UNLIMITED
    assert ent.unlocks("teleportation") is None


def test_a_locked_tap_names_the_level(monkeypatch):
    from app.bot.handlers.reports import locked_text

    monkeypatch.setattr(settings, "pro_features", "export,market_report")
    text = locked_text(ent.FEATURE_MARKET_REPORT, "en")
    assert "Market report" in text
    assert "Profi" in text
