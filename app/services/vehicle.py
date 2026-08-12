"""Vehicle-aware market comparison.

Comparing a car's price against ALL cars in a search is misleading: a
120.000-km 2016 Model 3 and a 15.000-km 2023 Performance are not the same
market. When a batch looks like vehicles, the market reference for each car is
built only from comparable cars (similar mileage and registration year), so the
deal score means "cheap for a car like THIS one".
"""

from __future__ import annotations

from app.parsers.schemas import ParsedListing
from app.services.price_analysis import PriceStats, compute_price_stats

#: A batch counts as vehicles when at least this share carries car attributes.
VEHICLE_BATCH_THRESHOLD = 0.5
#: Comparable if mileage is within this ratio of the item's mileage.
MILEAGE_BAND = 0.4
#: Comparable if the registration year is within this many years.
YEAR_BAND = 2
#: Need at least this many comparable cars, else fall back to the whole batch.
MIN_COMPARABLES = 3


def is_vehicle_batch(listings: list[ParsedListing]) -> bool:
    """True if most listings in the batch carry vehicle attributes."""
    if not listings:
        return False
    vehicles = sum(1 for item in listings if item.is_vehicle)
    return vehicles / len(listings) >= VEHICLE_BATCH_THRESHOLD


def _is_comparable(item: ParsedListing, other: ParsedListing) -> bool:
    """Whether ``other`` is a fair price comparable for ``item``."""
    if other.price is None:
        return False
    if item.mileage_km is not None and other.mileage_km is not None:
        lo = item.mileage_km * (1 - MILEAGE_BAND)
        hi = item.mileage_km * (1 + MILEAGE_BAND)
        if not (lo <= other.mileage_km <= hi):
            return False
    if item.registration_year is not None and other.registration_year is not None:
        if abs(item.registration_year - other.registration_year) > YEAR_BAND:
            return False
    return True


def similar_market_stats(
    item: ParsedListing, batch: list[ParsedListing], fallback: PriceStats
) -> PriceStats:
    """Price stats from cars comparable to ``item``; fallback if too few."""
    comps = [
        other.price
        for other in batch
        if other is not item and _is_comparable(item, other)
    ]
    if len(comps) < MIN_COMPARABLES:
        return fallback
    return compute_price_stats(comps)
