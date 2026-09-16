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

from app.database.models import Listing, PriceHistory, SearchRule, User
from app.parsers import registry
from app.parsers.schemas import ParsedListing, SearchQuery
from app.config.settings import settings
from app.services import ai
from app.services.deal_scorer import score_listing
from app.services.dedup import filter_new_listings
from app.services.freshness import is_fresh_enough
from app.services.price_analysis import PriceStats, compute_price_stats
from app.services.flips import get_flip_min, passes_flip_mode
from app.services.relevance import filter_relevant
from app.services.vehicle import is_vehicle_batch, similar_market_stats
from app.services.repositories import ListingRepository

#: On the very first run of a rule everything is "new"; cap the flood.
FIRST_RUN_MAX_NOTIFICATIONS = 5
#: How far back stored prices feed the market-price estimate.
MARKET_WINDOW_DAYS = 30
#: Minimum absolute price decrease (EUR) that counts as a price drop.
PRICE_DROP_MIN_DELTA = 1.0
#: ...and at least this share of the price, so a 1 € dip on a 30.000 € car
#: does not re-notify while a real cut on a cheap item still does.
PRICE_DROP_MIN_PERCENT = 1.0
#: Below this many stored prices a rule is treated as "cold" and an item is
#: not compared against a sample that contains itself.
MIN_STORED_FOR_SELF_COMPARISON = 10


def price_drop_threshold(previous_price: float) -> float:
    """How much a price must fall before the user is told again."""
    return max(PRICE_DROP_MIN_DELTA, previous_price * PRICE_DROP_MIN_PERCENT / 100.0)


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

        # Market context: 30 days of stored prices plus the current batch —
        # far more stable than the current batch alone. Computed before the
        # price-drop pass so a dropped listing can be re-scored right away.
        stored_prices = await self.listings.recent_prices(
            rule.id, days=MARKET_WINDOW_DAYS
        )
        batch_prices = [p.price for p in parsed if p.price is not None]
        stats = compute_price_stats(stored_prices + batch_prices)

        # Price drops on listings we already know (matched by external id):
        # update the stored row, record a history point and re-notify.
        drops, seen_external = await self._detect_price_drops(rule, parsed, stats)

        # Only genuinely unseen ads may become new rows. A price change alters
        # the fingerprint, so the external-id check prevents duplicate rows.
        candidates = [
            p for p in parsed if (p.site, p.external_id) not in seen_external
        ]
        fresh = filter_new_listings(candidates, known)
        if not fresh and not drops:
            logger.debug("Rule {}: no new listings after dedup", rule.id)
            return []

        # For vehicle searches, compare each car only against comparable cars
        # (similar mileage + year), so the score means "cheap for a car
        # like THIS one" instead of "cheap vs. all listings".
        vehicles = is_vehicle_batch(parsed)

        # On a cold rule the batch IS the market. Comparing an item against a
        # sample that contains itself pulls the median towards its own price,
        # so a genuine bargain could never score as one on first sighting.
        exclude_self = len(stored_prices) < MIN_STORED_FOR_SELF_COMPARISON

        new_rows: list[Listing] = []
        pairs: list[tuple[ParsedListing, Listing]] = []
        for item in fresh:
            if vehicles:
                item_stats = similar_market_stats(item, parsed, stats)
            elif exclude_self and item.price is not None and len(batch_prices) > 2:
                peers = list(batch_prices)
                peers.remove(item.price)
                item_stats = compute_price_stats(stored_prices + peers)
            else:
                item_stats = stats
            row = self._to_row(rule.id, item, item_stats)
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

        # Freshness policy: month-old ads that are merely new TO THE BOT are
        # not deals. Stale rows are stored (their prices feed the market
        # stats) but marked notified so they can never be delivered later.
        notable: list[Listing] = []
        for item, row in pairs:
            if not is_fresh_enough(item, row.deal_score):
                row.notified = True
                continue
            if row.deal_score >= rule.min_deal_score:
                notable.append(row)
        notable.sort(key=lambda r: r.deal_score, reverse=True)

        # First run seeds the baseline: send only the top few instead of
        # flooding the user with every existing listing.
        if first_run and len(notable) > FIRST_RUN_MAX_NOTIFICATIONS:
            skipped = notable[FIRST_RUN_MAX_NOTIFICATIONS:]
            for row in skipped:
                row.notified = True  # baseline: never deliver these later
            notable = notable[:FIRST_RUN_MAX_NOTIFICATIONS]

        # Cross-rule dedup: if another rule of the same user already delivered
        # this exact ad, do not send it a second time.
        if notable:
            already = await self.listings.notified_elsewhere(
                rule.user_id,
                rule.id,
                [row.external_id for row in notable],
            )
            if already:
                for row in notable:
                    if (row.site, row.external_id) in already:
                        row.notified = True
                notable = [
                    r for r in notable if (r.site, r.external_id) not in already
                ]

        # Price drops are always worth telling the user about.
        result = drops + notable

        # Flip-only mode: the owner wants ONLY listings whose estimated net
        # profit after fees reaches their threshold (set in /flips).
        if result:
            owner = await self.session.get(User, rule.user_id)
            min_net = await get_flip_min(owner.telegram_id) if owner else None
            if min_net:
                kept = [
                    r for r in result
                    if passes_flip_mode(r.price, r.estimated_market_price, min_net)
                ]
                for row in result:
                    if row not in kept:
                        row.notified = True  # below the flip threshold, never deliver
                result = kept
        return result

    async def _detect_price_drops(
        self,
        rule: SearchRule,
        parsed: list[ParsedListing],
        stats: PriceStats | None = None,
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
            threshold = (
                price_drop_threshold(row.price) if row.price is not None else 0.0
            )
            if row.price is not None and item.price < row.price - threshold:
                # Keep the pre-drop price for the "reduced from X" card line.
                row.original_price = row.price
                row.price = item.price
                row.notified = False
                # The score was computed for the OLD price. Without this the
                # card shows "price drop" next to a stale "overpriced" badge.
                if stats is not None:
                    self._rescore(row, item, stats)
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
            elif row.price is None or item.price > row.price + threshold:
                # Price increases (or first-seen prices) update the stored row
                # and the history quietly — no notification, but the data stays
                # honest for market statistics and the price chart.
                row.price = item.price
                self.session.add(
                    PriceHistory(
                        listing_id=row.id, price=item.price, currency=row.currency
                    )
                )
        return drops, seen

    # --- Internals ----------------------------------------------------------
    @staticmethod
    def _build_query(rule: SearchRule) -> SearchQuery:
        return SearchQuery(
            keywords=rule.keywords,
            exclude_keywords=list(rule.exclude_keywords or []),
            category=rule.category,
            min_price=rule.min_price,
            max_price=rule.max_price,
            condition=rule.condition,
            location=rule.location,
            zip_code=rule.zip_code,
            max_distance_km=rule.max_distance_km,
            exclude_auctions=rule.exclude_auctions,
            shipping_available=rule.shipping_available,
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

    @staticmethod
    def _rescore(row: Listing, item: ParsedListing, stats: PriceStats) -> None:
        """Refresh a stored row's verdict after its price changed."""
        deal = score_listing(item, stats)
        row.deal_score = deal.score
        row.deal_verdict = deal.verdict
        row.estimated_market_price = deal.estimated_market_price
        row.discount_percent = deal.discount_percent

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
            is_negotiable=item.is_negotiable,
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
