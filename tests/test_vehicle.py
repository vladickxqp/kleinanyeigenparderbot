"""Tests for structured vehicle attributes and spec-aware market comparison."""

from __future__ import annotations

from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing
from app.parsers.sites.kleinanzeigen import KleinanzeigenParser
from app.services.price_analysis import compute_price_stats
from app.services.vehicle import is_vehicle_batch, similar_market_stats


# --- Tag parsing ------------------------------------------------------------------
def test_parse_vehicle_tags():
    parse = KleinanzeigenParser._parse_vehicle_tags
    assert parse(["74.000 km", "EZ 12/2020", "Automatik"]) == (74000, 2020)
    assert parse(["EZ 2019", "150.000 km"]) == (150000, 2019)
    assert parse(["Erstzulassung 2022"]) == (None, 2022)


def test_parse_vehicle_tags_ignores_non_vehicle():
    parse = KleinanzeigenParser._parse_vehicle_tags
    # "5 km entfernt" is a distance, not mileage.
    assert parse(["5 km entfernt"]) == (None, None)
    assert parse(["Versand möglich", "Neuwertig"]) == (None, None)


# --- Batch detection --------------------------------------------------------------
def _car(price, km=None, year=None, ext="x") -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id=ext,
        title="Tesla Model 3",
        url="https://www.kleinanzeigen.de/x",
        price=price,
        mileage_km=km,
        registration_year=year,
    )


def test_is_vehicle_batch():
    cars = [_car(20000, 50000, 2021), _car(25000, 40000, 2022), _car(30000)]
    assert is_vehicle_batch(cars) is True

    phones = [_car(900), _car(800), _car(1000)]  # no km/year -> not vehicles
    assert is_vehicle_batch(phones) is False
    assert is_vehicle_batch([]) is False


# --- Spec-aware comparison --------------------------------------------------------
def test_similar_market_stats_uses_comparable_cars():
    # Target: 45k km, 2021. Comparables should be the other ~45k/2021 cars,
    # NOT the high-mileage old ones that drag the median down.
    target = _car(30000, 45000, 2021, ext="t")
    batch = [
        target,
        _car(31000, 48000, 2021),   # comparable
        _car(29000, 42000, 2022),   # comparable
        _car(32000, 50000, 2020),   # comparable
        _car(12000, 180000, 2016),  # NOT comparable (old, high km)
        _car(11000, 200000, 2015),  # NOT comparable
    ]
    fallback = compute_price_stats([c.price for c in batch])
    spec = similar_market_stats(target, batch, fallback)

    # The spec-aware median sits around the comparable cars (~31k), well above
    # the whole-batch median which the cheap old cars pull down.
    assert spec.median is not None
    assert spec.median > fallback.median
    assert 29000 <= spec.median <= 32000


def test_similar_market_stats_falls_back_when_too_few():
    target = _car(30000, 45000, 2021, ext="t")
    batch = [target, _car(12000, 180000, 2016)]  # only 1 non-comparable
    fallback = compute_price_stats([30000, 12000])
    result = similar_market_stats(target, batch, fallback)
    assert result is fallback
