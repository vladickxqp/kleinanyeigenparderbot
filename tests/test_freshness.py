"""Tests for posting-date parsing and the freshness notification policy."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing
from app.parsers.sites.kleinanzeigen import KleinanzeigenParser
from app.services.freshness import is_fresh_enough

NOW = datetime(2026, 7, 6, 12, 0)


# --- Date parsing (live formats verified 2026-07) --------------------------------
def test_parse_heute_and_gestern():
    parse = KleinanzeigenParser._parse_posted_date
    today = parse("Heute, 08:01")
    assert today is not None and today.hour == 8 and today.minute == 1
    assert today.date() == datetime.now().date()

    yesterday = parse("Gestern, 21:08")
    assert yesterday is not None
    assert yesterday.date() == (datetime.now() - timedelta(days=1)).date()


def test_parse_absolute_date():
    parsed = KleinanzeigenParser._parse_posted_date("04.07.2026")
    assert parsed == datetime(2026, 7, 4, 12, 0)


def test_promoted_top_ads_have_no_date():
    parse = KleinanzeigenParser._parse_posted_date
    assert parse("") is None
    assert parse(None) is None
    assert parse("TOP") is None


def test_sortierung_neueste_in_url():
    parser = KleinanzeigenParser()
    from app.parsers.schemas import SearchQuery

    url = parser._build_url(SearchQuery(keywords="tesla model 3"))
    assert "sortierung:neueste" in url


# --- Freshness policy --------------------------------------------------------------
def _kl_item(posted_at: datetime | None) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id="1",
        title="Tesla Model 3",
        url="https://www.kleinanzeigen.de/x",
        price=30000.0,
        posted_at=posted_at,
    )


def test_fresh_ad_always_notifies():
    item = _kl_item(NOW - timedelta(hours=3))
    assert is_fresh_enough(item, deal_score=0, now=NOW) is True


def test_two_day_old_ad_needs_good_score():
    item = _kl_item(NOW - timedelta(days=2))
    assert is_fresh_enough(item, deal_score=50, now=NOW) is False
    assert is_fresh_enough(item, deal_score=75, now=NOW) is True


def test_month_old_ad_never_notifies():
    item = _kl_item(NOW - timedelta(days=30))
    assert is_fresh_enough(item, deal_score=100, now=NOW) is False


def test_undated_kleinanzeigen_ad_is_treated_as_old():
    # Promoted TOP ads carry no date — they are old inventory.
    assert is_fresh_enough(_kl_item(None), deal_score=100, now=NOW) is False


def test_sites_without_dates_keep_old_behaviour():
    item = ParsedListing(
        site=SiteName.EBAY,
        external_id="1",
        title="Tesla Model 3",
        url="https://www.ebay.de/itm/123456789",
        price=30000.0,
        posted_at=None,
    )
    assert is_fresh_enough(item, deal_score=0, now=NOW) is True
