"""Regression test: oversized scraped strings must not crash the DB insert.

A single Kleinanzeigen ad with an oversized location string caused
``StringDataRightTruncationError: value too long for character varying(128)``
and killed the whole search run. All string fields are clipped to their column
lengths when converting a ParsedListing into a Listing row.
"""

from __future__ import annotations

from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing
from app.services.price_analysis import compute_price_stats
from app.services.search_service import SearchService, _clip


def test_to_row_clips_all_string_fields_to_column_lengths():
    item = ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id="x" * 500,
        title="Tesla Model 3 " + "sehr lang " * 100,
        url="https://www.kleinanzeigen.de/s-anzeige/" + "a" * 50,
        price=30000.0,
        location="Worms " * 60,          # > 128 chars — the real-world crash
        seller_name="Autohaus " * 40,    # > 128 chars
    )
    row = SearchService(None)._to_row(1, item, compute_price_stats([30000.0]))

    assert len(row.external_id) <= 128
    assert len(row.title) <= 512
    assert len(row.url) <= 1024
    assert row.location is not None and len(row.location) <= 128
    assert row.seller_name is not None and len(row.seller_name) <= 128
    assert len(row.currency) <= 3


def test_clip_collapses_whitespace_and_handles_none():
    assert _clip(None, 10) is None
    assert _clip("  a\n\n  b\t c  ", 100) == "a b c"
    assert _clip("x" * 50, 10) == "x" * 10
