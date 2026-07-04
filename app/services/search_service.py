"""Orchestrates a full scrape-analyse-persist cycle for one search rule.

This is the heart of the pipeline used by the Celery worker:

    rule -> SearchQuery -> parsers (concurrent) -> dedup -> price stats ->
    deal scoring -> persist new Listings -> return notable new listings.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Listing, SearchRule
from app.parsers import registry
from app.parsers.schemas import ParsedListing, SearchQuery
from app.config.settings import settings
from app.services import ai
from app.services.deal_scorer import score_listing
from app.services.dedup import filter_new_listings
from app.services.price_analysis import PriceStats, compute_price_stats
from app.services.repositories import ListingRepository


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

        known = await self.listings.existing_fingerprints(rule.id)
        fresh = filter_new_listings(parsed, known)
        if not fresh:
            logger.debug("Rule {}: no new listings after dedup", rule.id)
            return []

        # Build a market sample from *all* parsed prices this run for context.
        sample_prices = [p.price for p in parsed if p.price is not None]
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
        logger.info(
            "Rule {} ({}): +{} new listing(s)", rule.id, rule.name, len(new_rows)
        )

        # Only surface listings that clear the user's minimum score threshold.
        notable = [r for r in new_rows if r.deal_score >= rule.min_deal_score]
        notable.sort(key=lambda r: r.deal_score, reverse=True)
        return notable

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
            external_id=item.external_id,
            fingerprint=item.fingerprint,
            title=item.title,
            description=item.description,
            url=str(item.url),
            image_url=str(item.image_url) if item.image_url else None,
            price=item.price,
            original_price=item.original_price,
            currency=item.currency,
            shipping_cost=item.shipping_cost,
            condition=item.condition,
            location=item.location,
            seller_name=item.seller_name,
            seller_rating=item.seller_rating,
            is_auction=item.is_auction,
            deal_score=deal.score,
            deal_verdict=deal.verdict,
            estimated_market_price=deal.estimated_market_price,
            discount_percent=deal.discount_percent,
        )
