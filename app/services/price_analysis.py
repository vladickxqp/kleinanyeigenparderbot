"""Price statistics and anomaly detection.

Given a set of observed prices for comparable items, compute descriptive stats
and flag anomalously low prices (a "steal" — possibly a seller mistake).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(slots=True)
class PriceStats:
    """Descriptive statistics for a group of comparable prices."""

    count: int
    minimum: float | None
    maximum: float | None
    average: float | None
    median: float | None
    stdev: float | None

    @property
    def has_data(self) -> bool:
        return self.count > 0 and self.median is not None

    def discount_percent(self, price: float) -> float | None:
        """How far below the median a given price sits, as a percentage."""
        if not self.has_data or self.median in (None, 0):
            return None
        return round((1 - price / self.median) * 100, 1)

    def is_anomaly(self, price: float, z_threshold: float = 2.0) -> bool:
        """True if ``price`` is suspiciously low vs. the sample distribution."""
        if not self.has_data or self.average is None:
            return False
        if self.stdev in (None, 0):
            # No spread: treat >35% under median as anomalous.
            return price < (self.median or 0) * 0.65
        z = (price - self.average) / self.stdev  # type: ignore[operator]
        return z <= -z_threshold


def compute_price_stats(prices: list[float]) -> PriceStats:
    """Build :class:`PriceStats` from raw prices, ignoring None/<=0 values."""
    clean = [p for p in prices if p is not None and p > 0]
    if not clean:
        return PriceStats(0, None, None, None, None, None)
    return PriceStats(
        count=len(clean),
        minimum=min(clean),
        maximum=max(clean),
        average=round(statistics.fmean(clean), 2),
        median=round(statistics.median(clean), 2),
        stdev=round(statistics.pstdev(clean), 2) if len(clean) > 1 else 0.0,
    )
