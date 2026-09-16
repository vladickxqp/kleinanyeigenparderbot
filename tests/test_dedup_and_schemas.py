"""Tests for parsed-listing fingerprints and deduplication."""

from __future__ import annotations

from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing, SearchQuery
from app.services.dedup import dedup_within_batch, filter_new_listings


def _listing(
    title: str, price: float | None = 100.0, external_id: str | None = None
) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id=external_id or title,
        title=title,
        url="https://www.kleinanzeigen.de/x",
        price=price,
    )


def test_fingerprint_is_the_ad_identity():
    """Same ad id = same listing, regardless of title or price edits."""
    a = _listing("RTX 4090", 900, external_id="123")
    b = _listing("RTX 4090 OVP", 850, external_id="123")
    assert a.fingerprint == b.fingerprint


def test_different_ads_never_collide():
    """Two sellers, same generic title and price, must stay distinct.

    Hashing title+price made the second ad look "already known", so it was
    dropped without a trace — exactly the deals this bot exists to find.
    """
    a = _listing("PS5 Controller", 25.0, external_id="111")
    b = _listing("PS5 Controller", 25.0, external_id="222")
    assert a.fingerprint != b.fingerprint
    # As a repost signal the two are still recognised as the same offer.
    assert a.repost_fingerprint == b.repost_fingerprint


def test_repost_fingerprint_normalises_and_uses_price():
    assert (
        _listing("RTX  4090!!", 100, external_id="1").repost_fingerprint
        == _listing("rtx 4090", 100, external_id="2").repost_fingerprint
    )
    assert (
        _listing("card", 100, external_id="1").repost_fingerprint
        != _listing("card", 200, external_id="1").repost_fingerprint
    )


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
