"""Everything worth knowing about ONE listing, gathered in one place.

The deal card answers "is this cheap?" with a single number. That number is
only as good as what it was compared against, and the card never shows what
that was. This module opens it up:

* the full description, so the defect nobody mentions in the title is visible
  before anyone writes to a seller;
* the price history of this exact ad, so a "reduced" price that was reduced
  from a price nobody ever paid is obvious;
* what comparable ads are ASKING right now;
* and what comparable ads actually SOLD for (see :mod:`app.services.sold_comps`)
  — the only number in this product that reflects a buyer, not a hope.

**Comparable means the same KIND of thing**, not merely the same search. A
broken iPhone is not a data point for a working one, and a replacement display
is not a data point for either; comparing across those is how a rule reports a
"steal" that is simply a different product. The buckets are therefore:

* defective vs working — from the ad TEXT, not only the stored condition,
  because the text is where "Display defekt" hides; and
* spare part vs whole unit, which the price statistics already split on.

Vehicles are matched by rule and bucket only. Mileage and registration year
live in the parsed listing, not in the stored row, so a used-car band cannot
be applied here without a schema change — better to say so than to imply a
precision that is not there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Listing, PriceHistory
from app.database.models.enums import Condition
from app.parsers.sites.kleinanzeigen import defect_markers, guess_condition
from app.services.price_analysis import PriceStats, compute_price_stats
from app.services.relevance import is_part_listing

#: Fewer comparables than this and a median says nothing; the section is
#: shown as "not enough data" rather than as a number with false authority.
MIN_COMPARABLES = 3
#: How many price points a chart gets. A year of daily observations would be
#: unreadable on a phone and is not what a price chart is for.
MAX_HISTORY_POINTS = 60


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One observed price of this ad."""

    at: datetime
    price: float


@dataclass(slots=True)
class Comparison:
    """What comparable ads cost, and where this one sits among them."""

    stats: PriceStats
    #: How far below (positive) or above (negative) the median this ad is.
    discount_percent: float | None = None

    @property
    def usable(self) -> bool:
        return self.stats.count >= MIN_COMPARABLES and self.stats.median is not None


@dataclass(slots=True)
class ListingDetail:
    """One listing, with the context the deal score was computed from."""

    listing: Listing
    #: Defect evidence found in title + description, e.g. ["defekt", "bastler"].
    defect_markers: list[str] = field(default_factory=list)
    #: What the ad TEXT says the condition is — may differ from the stored one.
    text_condition: Condition = Condition.USED
    #: This ad's own price over time, oldest first.
    history: list[PricePoint] = field(default_factory=list)
    #: What comparable ads are asking right now.
    asking: Comparison | None = None
    #: What comparable ads actually sold for.
    sold: Comparison | None = None
    #: How many ads the comparison was drawn from, before the minimum.
    compared_with: int = 0
    is_part: bool = False

    @property
    def is_defective(self) -> bool:
        return bool(self.defect_markers) or self.text_condition is Condition.DEFECTIVE

    @property
    def price_fell(self) -> float | None:
        """How much this ad came down since it was first seen, if it did."""
        if len(self.history) < 2:
            return None
        first, last = self.history[0].price, self.history[-1].price
        return first - last if first > last else None

    @property
    def best_reference(self) -> Comparison | None:
        """Sold prices when there are enough, else asking prices.

        A realised price is what somebody paid; an asking price is what
        somebody hopes for. Preferring the first whenever it exists is the
        whole reason sold comparables are collected.
        """
        if self.sold is not None and self.sold.usable:
            return self.sold
        if self.asking is not None and self.asking.usable:
            return self.asking
        return None


def _bucket(listing: Listing) -> tuple[bool, bool]:
    """(is defective, is a spare part) — what makes two ads comparable."""
    condition = guess_condition(listing.title, listing.description)
    defective = (
        condition is Condition.DEFECTIVE or listing.condition is Condition.DEFECTIVE
    )
    return defective, is_part_listing(listing.title)


def _compare(price: float | None, prices: list[float]) -> Comparison:
    stats = compute_price_stats(prices)
    discount = (
        stats.discount_percent(price)
        if price is not None and stats.has_data
        else None
    )
    return Comparison(stats=stats, discount_percent=discount)


async def build(
    session: AsyncSession, listing: Listing, *, now: datetime | None = None
) -> ListingDetail:
    """Gather description, price history and comparables for one listing."""
    markers = defect_markers(listing.title, listing.description)
    detail = ListingDetail(
        listing=listing,
        defect_markers=markers,
        text_condition=guess_condition(listing.title, listing.description),
        is_part=is_part_listing(listing.title),
    )

    # --- This ad's own price over time ------------------------------------
    rows = (
        await session.execute(
            select(PriceHistory.observed_at, PriceHistory.price)
            .where(PriceHistory.listing_id == listing.id)
            .order_by(PriceHistory.observed_at.asc())
        )
    ).all()
    points = [PricePoint(at=at, price=price) for at, price in rows if price is not None]
    if len(points) > MAX_HISTORY_POINTS:
        # Keep the ends and thin the middle: the first and the current price
        # are the two a reader actually looks for.
        step = len(points) / (MAX_HISTORY_POINTS - 1)
        kept = [points[int(i * step)] for i in range(MAX_HISTORY_POINTS - 1)]
        kept.append(points[-1])
        points = kept
    detail.history = points

    # --- Comparable ads of the SAME kind -----------------------------------
    defective, part = _bucket(listing)
    siblings = (
        await session.execute(
            select(Listing).where(
                Listing.rule_id == listing.rule_id,
                Listing.id != listing.id,
                Listing.price.is_not(None),
            )
        )
    ).scalars().all()

    same_kind = [
        other
        for other in siblings
        if _bucket(other) == (defective, part)
    ]
    detail.compared_with = len(same_kind)
    detail.asking = _compare(listing.price, [o.price for o in same_kind if o.price])

    # --- What comparable ads actually sold for ------------------------------
    sold_prices = await _sold_prices(session, listing, (defective, part), now=now)
    if sold_prices:
        detail.sold = _compare(listing.price, sold_prices)
    return detail


async def _sold_prices(
    session: AsyncSession,
    listing: Listing,
    bucket: tuple[bool, bool],
    *,
    now: datetime | None = None,
) -> list[float]:
    """Realised prices of comparable ads under the same rule.

    A realised price belongs to a listing that has since disappeared; the row
    may well have been swept away by retention. Those that are still here are
    bucketed like everything else, and the rest are used as they are — a
    realised price is too scarce to throw away for want of a title.
    """
    from app.services import sold_comps

    try:
        comps = await sold_comps.realised_comps(listing.rule_id, now=now)
    except Exception as exc:  # noqa: BLE001 - context must never break the page
        logger.debug("listing_detail: sold comps unavailable: {}", exc)
        return []
    if not comps:
        return []

    by_id = {comp.listing_id: comp.price for comp in comps}
    rows = (
        await session.execute(select(Listing).where(Listing.id.in_(list(by_id))))
    ).scalars().all()
    known = {row.id for row in rows}

    prices = [price for listing_id, price in by_id.items() if listing_id not in known]
    prices += [by_id[row.id] for row in rows if _bucket(row) == bucket]
    return prices
