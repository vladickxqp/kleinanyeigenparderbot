"""Deal scoring: turn a listing + market context into a 0-100 score and verdict.

The heuristic scorer is always available and deterministic. If ``AI_ENABLED`` is
set and an API key is present, an optional AI pass can refine the score (wired in
``app.services.ai`` in a later phase); the heuristic is used as a robust fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.database.models.enums import DealVerdict
from app.parsers.schemas import ParsedListing
from app.services.price_analysis import PriceStats


@dataclass(slots=True)
class DealResult:
    """Outcome of scoring a single listing."""

    score: int
    verdict: DealVerdict
    estimated_market_price: float | None
    discount_percent: float | None

    @property
    def is_notable(self) -> bool:
        return self.verdict in (DealVerdict.GOOD, DealVerdict.GREAT, DealVerdict.STEAL)


class DealScorer:
    """Heuristic deal scorer based on price position within a market sample."""

    def score(self, listing: ParsedListing, stats: PriceStats) -> DealResult:
        price = listing.total_price if listing.total_price is not None else listing.price

        # No price or no market context -> neutral, unknown.
        if price is None or not stats.has_data:
            return DealResult(50, DealVerdict.UNKNOWN, stats.median, None)

        discount = stats.discount_percent(price)
        anomaly = stats.is_anomaly(price)

        score = self._score_from_discount(discount, anomaly)
        # Shrink towards neutral while the sample is thin. A 40 % discount off
        # a median computed from ONE other ad is not a 90-point deal, it is a
        # guess — and the old scorer stated it as confidently as one drawn
        # from fifty comparisons.
        score = self._apply_confidence(score, stats.confidence)
        verdict = self._verdict_from_score(score, anomaly)

        return DealResult(
            score=score,
            verdict=verdict,
            estimated_market_price=stats.median,
            discount_percent=discount,
        )

    # --- Internals ----------------------------------------------------------
    @staticmethod
    def _score_from_discount(discount: float | None, anomaly: bool) -> int:
        """Map discount% (below median) to a 0-100 score.

        0% discount -> ~50, 50% discount -> ~100. Anomalies get a boost.
        """
        base = 50.0 if discount is None else 50.0 + discount  # discount can be <0
        if anomaly:
            base += 15
        return int(max(0, min(100, round(base))))

    @staticmethod
    def _apply_confidence(score: int, confidence: float) -> int:
        """Pull a score towards 50 in proportion to how little is known.

        Full confidence leaves it untouched. With a single comparable the
        score barely leaves neutral, which is the honest answer: the market
        is unknown, not generous.
        """
        if confidence >= 1.0:
            return score
        return int(round(50 + (score - 50) * max(0.0, confidence)))

    @staticmethod
    def _verdict_from_score(score: int, anomaly: bool) -> DealVerdict:
        if anomaly and score >= 85:
            return DealVerdict.STEAL
        if score >= 85:
            return DealVerdict.GREAT
        if score >= 70:
            return DealVerdict.GOOD
        if score >= 45:
            return DealVerdict.FAIR
        return DealVerdict.OVERPRICED


_default_scorer = DealScorer()


def score_listing(listing: ParsedListing, stats: PriceStats) -> DealResult:
    """Convenience wrapper using the default heuristic scorer."""
    return _default_scorer.score(listing, stats)
