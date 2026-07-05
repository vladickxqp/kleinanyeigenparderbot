"""Orchestrates a full scrape-analyse-persist cycle for one search rule.

This is the heart of the pipeline used by the Celery worker:

    rule -> SearchQuery -> parsers (concurrent) -> relevance filter ->
    price-drop detection on known listings -> dedup -> 30-day market stats ->
    deal scoring -> persist new Listings + PriceHistory -> notable results.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Listing, PriceHistory, SearchRule
from app.parsers import registry
from app.parsers.schemas import ParsedListing, SearchQuery
from app.config.settings import settings
from app.services import ai
from app.services.deal_scorer import score_listing
from app.services.dedup import filter_new_listings
from app.services.price_analysis import PriceStats, compute_price_stats
from app.services.relevance import filter_relevant
from app.services.repositories import ListingRepository

#: On the very first run of a rule everything is "new"; cap the flood.
FIRST_RUN_MAX_NOTIFICATIONS = 5
#: How far back stored prices feed the market-price estimate.
MARKET_WINDOW_DAYS = 30
#: Minimum absolute price decrease (EUR) that counts as a price drop.
PRICE_DROP_MIN_DELTA = 1.0


class SearchService:
    """Runs one search rule end-to-end against all its target parsers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.listings = ListingRepository(session)

    # --- Public API ---------------------------------------------------------
    async def run_rule(self, rule: SearchRule) -> list[Listing]:
        """Execute ``rule``, persist new listings, return notable new ones."""
        query = self._build_query(rule)
        parsed = await self._collect(rule, query)
        if not parsed:
            return []

        # Drop accessories, wanted-ads and off-topic hits BEFORE price stats,
        # so a 15€ phone case never looks like a "steal" next to real phones.
        parsed = filter_relevant(query, parsed)
        if not parsed:
            logger.debug("Rule {}: nothing relevant after filtering", rule.id)
            return []

        known = await self.listings.existing_fingerprints(rule.id)
        first_run = not known

        # Price drops on listings we already know (matched by external id):
        # update the stored row, record a history point and re-notify.
        drops, seen_external = await self._detect_price_drops(rule, parsed)

        # Only genuinely unseen ads may become new rows. A price change alters
        # the fingerprint, so the external-id check prevents duplicate rows.
        candidates = [
            p for p in parsed if (p.site, p.external_id) not in seen_external
        ]
        fresh = filter_new_listings(candidates, known)
        if not fresh and not drops:
            logger.debug("Rule {}: no new listings after dedup", rule.id)
            return []

        # Market context: 30 days of stored prices plus the current batch —
        # far more stable than the current batch alone.
        stored_prices = await self.listings.recent_prices(
            rule.id, days=MARKET_WINDOW_DAYS
        )
        sample_prices = stored_prices + [
            p.price for p in parsed if p.price is not None
        ]
        stats = compute_price_stats(sample_prices)

        new_rows: list[Listing] = []
        pairs: list[tuple[ParsedListing, Listing]] = []
        for item in fresh:
            row = self._to_row(rule.id, item, stats)
            new_rows.append(row)
            pairs.append((item, row))

        # Optional AI refinement on listings that already look promising, to
        # avoid spending tokens on obvious non-deals.
        if ai.is_available():
            await self._refine_with_ai(pairs, stats, rule.min_deal_score)

        await self.listings.add_all(new_rows)

        # Seed the price history for every new listing that has a price.
        for row in new_rows:
            if row.price is not None:
                self.session.add(
                    PriceHistory(
                        listing_id=row.id, price=row.price, currency=row.currency
                    )
                )

        logger.info(
            "Rule {} ({}): +{} new, {} price drop(s)",
            rule.id, rule.name, len(new_rows), len(drops),
        )

        # Only surface listings that clear the user's minimum score threshold.
        notable = [r for r in new_rows if r.deal_score >= rule.min_deal_score]
        notable.sort(key=lambda r: r.deal_score, reverse=True)

        # First run seeds the baseline: send only the top few instead of
        # flooding the user with every existing listing.
        if first_run and len(notable) > FIRST_RUN_MAX_NOTIFICATIONS:
            skipped = notable[FIRST_RUN_MAX_NOTIFICATIONS:]
            for row in skipped:
                row.notified = True  # baseline: never deliver these later
            notable = notable[:FIRST_RUN_MAX_NOTIFICATIONS]

        # Price drops are always worth telling the user about.
        return drops + notable

    async def _detect_price_drops(
        self, rule: SearchRule, parsed: list[ParsedListing]
    ) -> tuple[list[Listing], set[tuple[object, str]]]:
        """Compare current prices of known ads against the stored rows.

        Returns the re-notifiable dropped listings and the set of
        ``(site, external_id)`` pairs that already exist for this rule.
        """
        by_ext = {
            (item.site, item.external_id): item
            for item in parsed
            if item.external_id
        }
        if not by_ext:
            return [], set()

        existing = await self.listings.by_external_ids(
            rule.id, [ext for _, ext in by_ext]
        )
        seen: set[tuple[object, str]] = set()
        drops: list[Listing] = []
        for row in existing:
            key = (row.site, row.external_id)
            seen.add(key)
            item = by_ext.get(key)
            if item is None or item.price is None:
                continue
            if row.price is not None and item.price < row.price - PRICE_DROP_MIN_DELTA:
                # Keep the pre-drop price for the "reduced from X" card line.
                row.original_price = row.price
                row.price = item.price
                row.notified = False
                self.session.add(
                    PriceHistory(
                        listing_id=row.id, price=item.price, currency=row.currency
                    )
                )
                drops.append(row)
                logger.info(
                    "Rule {}: price drop '{}' {} -> {}",
                    rule.id, row.title[:40], row.original_price, row.price,
                )
        return drops, seen

    # --- Internals ----------------------------------------------------------
    @staticmethod
    def _build_query(rule: SearchRule) -> SearchQuery:
        return SearchQuery(
            keywords=rule.keywords,
            exclude_keywords=list(rule.exclude_keywords or []),
            category=rule.category,
            brand=rule.brand,
            min_price=rule.min_price,
            max_price=rule.max_price,
            condition=rule.condition,
            location=rule.location,
            zip_code=rule.zip_code,
            max_distance_km=rule.max_distance_km,
            exclude_auctions=rule.exclude_auctions,
        )

    async def _collect(
        self, rule: SearchRule, query: SearchQuery
    ) -> list[ParsedListing]:
        parsers = registry.resolve(rule.target_sites)
        if not parsers:
            logger.warning("Rule {}: no parsers resolved", rule.id)
            return []

        results = await asyncio.gather(
            *(p.collect(query) for p in parsers), return_exceptions=True
        )
        parsed: list[ParsedListing] = []
        for res in results:
            if isinstance(res, BaseException):
                logger.error("Parser raised during gather: {}", res)
                continue
            parsed.extend(res)
        return parsed

    async def _refine_with_ai(
        self,
        pairs: list[tuple[ParsedListing, Listing]],
        stats: PriceStats,
        min_score: int,
    ) -> None:
        """Refine promising listings' scores with the AI scorer, in place."""
        # Only spend AI budget on things at least close to the notify threshold.
        candidates = [(i, r) for i, r in pairs if r.deal_score >= max(0, min_score - 10)]
        for item, row in candidates:
            result = await ai.score_listing_ai(item, stats)
            if result is None:
                continue
            row.deal_score = result.score
            row.deal_verdict = result.verdict
            logger.debug(
                "AI refined '{}' -> {}/{}", item.title[:40], result.score,
                result.verdict.value,
            )

    def _to_row(self, rule_id: int, item: ParsedListing, stats: PriceStats) -> Listing:
        deal = score_listing(item, stats)
        return Listing(
            rule_id=rule_id,
            site=item.site,
            external_id=_clip(item.external_id, 128) or "",
            fingerprint=item.fingerprint,
            title=_clip(item.title, 512) or "(kein Titel)",
            description=item.description,
            url=_clip(str(item.url), 1024) or "",
            image_url=_clip(str(item.image_url), 1024) if item.image_url else None,
            price=item.price,
            original_price=item.original_price,
            currency=_clip(item.currency, 3) or "EUR",
            shipping_cost=item.shipping_cost,
            condition=item.condition,
            location=_clip(item.location, 128),
            seller_name=_clip(item.seller_name, 128),
            seller_rating=item.seller_rating,
            is_auction=item.is_auction,
            deal_score=deal.score,
            deal_verdict=deal.verdict,
            estimated_market_price=deal.estimated_market_price,
            discount_percent=deal.discount_percent,
        )


def _clip(value: str | None, limit: int) -> str | None:
    """Trim a scraped string to its DB column length.

    Marketplaces occasionally deliver pathological values (one oversized
    location string crashed a whole search run with
    ``StringDataRightTruncationError``); persisting a truncated value is
    always better than failing the entire scrape.
    """
    if value is None:
        return None
    value = " ".join(value.split())  # collapse runs of whitespace/newlines
    return value[:limit]
