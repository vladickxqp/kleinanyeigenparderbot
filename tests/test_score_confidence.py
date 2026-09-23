"""A verdict is only as good as the sample it was drawn from.

The scorer had no idea how much it knew. `has_data` meant "at least one price",
so a median computed from a SINGLE other ad produced the strongest claim this
product makes — 🔥 KRACHER, score 100 — identical in wording and confidence to
one drawn from fifty comparisons. On a rule's first run that is exactly what
happened, which is the worst possible moment to be wrong: it is the user's
first impression of whether the bot can be trusted.

These tests pin the confidence down: what a thin sample may claim, what it may
not, and that a real sample is untouched.
"""

from __future__ import annotations

import pytest

from app.config.settings import settings
from app.database.models.enums import DealVerdict, SiteName
from app.parsers.schemas import ParsedListing
from app.services.deal_scorer import score_listing
from app.services.price_analysis import compute_price_stats


def _ad(price: float) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN, external_id="x", title="PS5 Slim",
        url="https://example.com/x", price=price,
    )


def _score(price: float, comparables: list[float]):
    return score_listing(_ad(price), compute_price_stats(comparables))


# --- What a thin sample may not claim -----------------------------------------------
def test_one_comparable_is_not_a_market():
    # 300 against a single 500 used to be a steal with score 100.
    result = _score(300.0, [500.0])
    assert result.verdict is DealVerdict.FAIR
    assert result.score < 70


def test_confidence_grows_with_the_sample():
    scores = [_score(300.0, [500.0] * n).score for n in (1, 2, 3, 5)]
    assert scores == sorted(scores), scores
    assert scores[0] < scores[-1]


def test_a_real_sample_is_left_alone():
    result = _score(300.0, [450.0, 480.0, 500.0, 520.0, 560.0])
    assert result.verdict is DealVerdict.STEAL
    assert result.score == 100


def test_nothing_is_an_outlier_of_two_other_prices():
    """An anomaly needs a distribution to be an anomaly of."""
    thin = compute_price_stats([500.0, 520.0])
    assert thin.is_anomaly(300.0) is False
    full = compute_price_stats([450.0, 480.0, 500.0, 520.0, 560.0])
    assert full.is_anomaly(200.0) is True


def test_an_overpriced_ad_is_also_pulled_towards_neutral():
    """Shrinkage is not a discount for bargains — it cuts both ways."""
    thin = _score(900.0, [500.0])
    full = _score(900.0, [500.0] * 5)
    assert thin.score > full.score          # less sure it is bad, too
    assert full.verdict is DealVerdict.OVERPRICED


# --- The dial -----------------------------------------------------------------------
def test_the_threshold_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "min_confident_comparables", 2)
    # With the bar at two, two comparables are already a full sample.
    assert compute_price_stats([500.0, 520.0]).is_thin is False
    assert compute_price_stats([500.0]).is_thin is True


def test_confidence_is_a_share_of_what_is_needed(monkeypatch):
    monkeypatch.setattr(settings, "min_confident_comparables", 4)
    assert compute_price_stats([1.0]).confidence == 0.25
    assert compute_price_stats([1.0] * 4).confidence == 1.0
    # Never above 1: more than enough is still enough.
    assert compute_price_stats([1.0] * 40).confidence == 1.0


def test_no_prices_means_no_confidence_and_no_verdict():
    stats = compute_price_stats([])
    assert stats.confidence == 0.0
    assert stats.has_data is False
    assert score_listing(_ad(300.0), stats).verdict is DealVerdict.UNKNOWN


# --- The card says which of the two it is --------------------------------------------
def test_the_card_admits_a_thin_basis(monkeypatch):
    from app.bot.formatting import format_deal_card
    from app.database.models import Listing

    monkeypatch.setattr(settings, "min_confident_comparables", 5)
    row = Listing(
        rule_id=1, site=SiteName.KLEINANZEIGEN, external_id="1", fingerprint="f",
        title="PS5 Slim", url="https://example.com/1", price=300.0,
        estimated_market_price=500.0, deal_score=58,
        deal_verdict=DealVerdict.FAIR, market_sample=2,
    )
    card = format_deal_card(row, "de")
    assert "Marktpreis" in card
    assert "2 Vergleiche" in card


def test_a_solid_basis_needs_no_footnote(monkeypatch):
    from app.bot.formatting import format_deal_card
    from app.database.models import Listing

    monkeypatch.setattr(settings, "min_confident_comparables", 5)
    row = Listing(
        rule_id=1, site=SiteName.KLEINANZEIGEN, external_id="1", fingerprint="f",
        title="PS5 Slim", url="https://example.com/1", price=300.0,
        estimated_market_price=500.0, deal_score=100,
        deal_verdict=DealVerdict.STEAL, market_sample=47,
    )
    card = format_deal_card(row, "de")
    assert "Marktpreis" in card
    assert "Vergleiche" not in card


def test_a_row_scored_before_the_column_existed_says_nothing(monkeypatch):
    """Older rows carry no sample size; the card must not invent one."""
    from app.bot.formatting import format_deal_card
    from app.database.models import Listing

    row = Listing(
        rule_id=1, site=SiteName.KLEINANZEIGEN, external_id="1", fingerprint="f",
        title="PS5 Slim", url="https://example.com/1", price=300.0,
        estimated_market_price=500.0, deal_score=90,
        deal_verdict=DealVerdict.GREAT, market_sample=None,
    )
    card = format_deal_card(row, "de")
    assert "Marktpreis" in card
    assert "Vergleiche" not in card


def test_the_pipeline_records_what_it_compared_against():
    """Wired, not merely computed — the card can only say what was stored."""
    import inspect

    from app.services import search_service

    source = inspect.getsource(search_service.SearchService._to_row)
    assert "market_sample=stats.count" in source
