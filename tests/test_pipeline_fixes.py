"""Regressions for pipeline bugs that silently cost the user real deals."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.parsers.schemas import ParsedListing, SearchQuery
from app.database.models.enums import SiteName
from app.services.freshness import is_fresh_enough
from app.services.relevance import filter_relevant
from app.services.search_service import price_drop_threshold


def _item(title: str, **kwargs) -> ParsedListing:
    data = {
        "site": SiteName.KLEINANZEIGEN,
        "external_id": title,
        "title": title,
        "url": "https://www.kleinanzeigen.de/x",
        "price": 100.0,
        "posted_at": datetime.now(),
    }
    data.update(kwargs)
    return ParsedListing(**data)


def test_wireless_items_survive_the_accessory_filter():
    """"kabel" must not match inside "kabellose" — that dropped real hits."""
    query = SearchQuery(keywords="maus")
    items = [
        _item("Kabellose Maus Logitech"),
        _item("Maus kabellos, neuwertig"),
        _item("USB Kabel für Maus"),      # genuine accessory, still filtered
        _item("Ladekabel Maus"),          # compound accessory, still filtered
    ]
    kept = {item.title for item in filter_relevant(query, items)}
    assert kept == {"Kabellose Maus Logitech", "Maus kabellos, neuwertig"}


def test_accessory_word_still_filters_when_searched_alone():
    query = SearchQuery(keywords="iphone")
    items = [_item("iPhone 15 Hülle"), _item("iPhone 15 128GB")]
    kept = [item.title for item in filter_relevant(query, items)]
    assert kept == ["iPhone 15 128GB"]

    # ...unless the user explicitly wants the accessory.
    query = SearchQuery(keywords="iphone hülle")
    kept = [item.title for item in filter_relevant(query, items)]
    assert kept == ["iPhone 15 Hülle"]


def test_price_drop_threshold_scales_with_the_price():
    """A one-euro dip on a car is noise; on a cheap item it is a real cut."""
    assert price_drop_threshold(20.0) == 1.0          # floor applies
    assert price_drop_threshold(30_000.0) == 300.0    # 1 percent


def test_freshness_handles_aware_and_naive_timestamps():
    """Mixing timezone-aware and naive datetimes must never raise."""
    from datetime import timezone

    fresh = _item("x", posted_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert is_fresh_enough(fresh, deal_score=10) is True

    old = _item("y", posted_at=datetime.now(timezone.utc) - timedelta(days=10))
    assert is_fresh_enough(old, deal_score=99) is False


def test_undated_promoted_ads_are_never_fresh():
    assert is_fresh_enough(_item("promo", posted_at=None), deal_score=100) is False


def test_block_detection_marks_parser_unhealthy():
    """A captcha page (HTTP 200, no cards) must not count as a clean run."""
    import asyncio

    from app.parsers.sites.kleinanzeigen import KleinanzeigenParser

    parser = KleinanzeigenParser()
    reported: list[bool] = []

    async def fake_report(*, ok: bool) -> None:
        reported.append(ok)

    async def fake_search(query):  # noqa: ANN001
        # Simulate what _parse_results does on a block page.
        parser.mark_suspected_block()
        return []

    parser._report_health = fake_report  # type: ignore[assignment]
    parser.search = fake_search  # type: ignore[assignment]

    result = asyncio.run(parser.collect(SearchQuery(keywords="anything")))
    assert result == []
    assert reported == [False]


def test_empty_but_valid_result_page_counts_as_healthy():
    import asyncio

    from app.parsers.sites.kleinanzeigen import KleinanzeigenParser

    parser = KleinanzeigenParser()
    reported: list[bool] = []

    async def fake_report(*, ok: bool) -> None:
        reported.append(ok)

    async def fake_search(query):  # noqa: ANN001
        return []

    parser._report_health = fake_report  # type: ignore[assignment]
    parser.search = fake_search  # type: ignore[assignment]

    asyncio.run(parser.collect(SearchQuery(keywords="anything")))
    assert reported == [True]


def test_result_page_markers_detect_a_block():
    from app.parsers.sites.kleinanzeigen import KleinanzeigenParser

    parser = KleinanzeigenParser()
    query = SearchQuery(keywords="x")

    parser._parse_results("<html><body>Bitte bestätige, dass du kein Bot bist"
                          "</body></html>", query)
    assert parser._suspect_block is True

    parser._suspect_block = False
    parser._parse_results(
        '<html><body><div id="srchrslt-adtable"></div></body></html>', query
    )
    assert parser._suspect_block is False
