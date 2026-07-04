"""Tests for parsed-listing fingerprints and deduplication."""

from __future__ import annotations

from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing, SearchQuery
from app.services.dedup import dedup_within_batch, filter_new_listings


def _listing(title: str, price: float | None = 100.0) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id=title,
        title=title,
        url="https://www.kleinanzeigen.de/x",
        price=price,
    )


def test_fingerprint_is_stable_and_normalising():
    a = _listing("RTX  4090!!")
    b = _listing("rtx 4090")
    assert a.fingerprint == b.fingerprint


def test_fingerprint_differs_on_price():
    assert _listing("card", 100).fingerprint != _listing("card", 200).fingerprint


def test_dedup_within_batch_keeps_first():
    items = [_listing("a"), _listing("a"), _listing("b")]
    unique = dedup_within_batch(items)
    assert len(unique) == 2


def test_filter_new_listings_excludes_known():
    items = [_listing("a"), _listing("b")]
    known = {items[0].fingerprint}
    fresh = filter_new_listings(items, known)
    assert len(fresh) == 1
    assert fresh[0].title == "b"


def test_search_query_exclude_matching():
    q = SearchQuery(keywords="rtx 4090", exclude_keywords=["defekt", "kaputt"])
    assert q.matches_text("RTX 4090 neu") is True
    assert q.matches_text("RTX 4090 DEFEKT") is False
