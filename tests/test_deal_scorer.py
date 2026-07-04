"""Tests for the heuristic deal scorer."""

from __future__ import annotations

from app.database.models.enums import DealVerdict, SiteName
from app.parsers.schemas import ParsedListing
from app.services.deal_scorer import score_listing
from app.services.price_analysis import compute_price_stats


def _listing(price: float | None) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id="x",
        title="RTX 4090",
        url="https://www.kleinanzeigen.de/x",
        price=price,
    )


def test_unknown_without_price():
    stats = compute_price_stats([1000, 1100, 900])
    result = score_listing(_listing(None), stats)
    assert result.verdict is DealVerdict.UNKNOWN


def test_unknown_without_market_context():
    result = score_listing(_listing(500), compute_price_stats([]))
    assert result.verdict is DealVerdict.UNKNOWN


def test_fair_price_near_median():
    stats = compute_price_stats([1000, 1000, 1000])
    result = score_listing(_listing(1000), stats)
    assert result.verdict in (DealVerdict.FAIR, DealVerdict.GOOD)


def test_great_deal_well_below_market():
    stats = compute_price_stats([1000, 1000, 1000, 1000])
    result = score_listing(_listing(550), stats)
    assert result.score >= 85
    assert result.verdict in (DealVerdict.GREAT, DealVerdict.STEAL)


def test_overpriced_above_market():
    stats = compute_price_stats([1000, 1000, 1000])
    result = score_listing(_listing(1400), stats)
    assert result.verdict is DealVerdict.OVERPRICED
