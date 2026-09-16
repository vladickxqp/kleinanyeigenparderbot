"""Realised prices derived from ads that stopped appearing.

Every price this bot compares against is an ASKING price: what sellers want,
not what buyers paid. No marketplace here publishes realised prices, so the
market estimate is structurally optimistic — and a "20% under market" badge
computed from wishful asking prices is worth very little.

But the bot knows something the marketplaces do not publish either: which ads
DISAPPEARED. An ad that vanishes from its rule's results was, with very few
exceptions, sold — and its last known price is then a realised price. Two
guards keep that inference honest:

* an ad must be missing from ``settings.sold_comp_missing_runs`` runs in a row,
  so one failed scrape or one paginated result page proves nothing, and
* only ads younger than ``settings.sold_comp_max_age_days`` are judged, because
  an old ad may just as well have been withdrawn, expired or edited out of the
  rule's filters.

A run that saw NOTHING is ignored completely: a blocked parser looks exactly
like a market that sold out overnight, and marking a whole rule's inventory as
sold would poison the comparison set for weeks.

State lives in Redis, NOT in the database. The counter belongs in a column on
``listings``, but that means an ORM change in
``app/database/models/listing.py`` — a file this work package does not own — so
the honest fallback is Redis. What that costs: a Redis flush resets the missing
counters and drops recorded comparables, i.e. a rule needs a few more runs
before it recognises sales again. It cannot produce a WRONG price, only fewer
of them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Listing, SiteName
from app.services.price_analysis import PriceStats, compute_price_stats

#: Consecutive misses per listing, and the realised prices per rule.
MISSING_KEY = "soldcomp:missing:{rule_id}"
SOLD_KEY = "soldcomp:sold:{rule_id}"

#: Fallbacks, used only if the settings ever lose these keys.
DEFAULT_MISSING_RUNS = 3
DEFAULT_MAX_AGE_DAYS = 45


@dataclass(slots=True)
class SoldComp:
    """One ad that disappeared, at the price it last asked for."""

    listing_id: int
    price: float
    sold_at: datetime


@dataclass(slots=True)
class ObserveResult:
    """What one rule run changed in the sold-comparable bookkeeping."""

    seen: int = 0
    missing: int = 0
    sold: int = 0
    #: False when the run carried no evidence (disabled, or nothing scraped).
    counted: bool = False


def is_enabled() -> bool:
    return bool(getattr(settings, "sold_comps_enabled", False))


def _missing_runs() -> int:
    return max(1, int(getattr(settings, "sold_comp_missing_runs", DEFAULT_MISSING_RUNS)))


def _max_age_days() -> int:
    return max(1, int(getattr(settings, "sold_comp_max_age_days", DEFAULT_MAX_AGE_DAYS)))


@asynccontextmanager
async def _redis():
    """Short-lived connection, safe across the worker's per-task event loops."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive timestamps; every stored value is UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# --- Observing a run ------------------------------------------------------------
def watch(service: object) -> list[tuple[SiteName, str]]:
    """Collect every ``(site, external id)`` one rule run actually saw.

    The scrape pipeline has no hook of its own, so the collection step is
    wrapped for the lifetime of this service instance. Anything unexpected
    leaves the run completely untouched: a missing sold comparable costs one
    data point, a broken search run costs the user their deal.
    """
    seen: list[tuple[SiteName, str]] = []
    if not is_enabled():
        return seen

    original = getattr(service, "_collect", None)
    if original is None:  # pragma: no cover - only if the pipeline is renamed
        logger.debug("sold_comps.watch: no collection step to observe")
        return seen

    async def collecting(rule, query):  # noqa: ANN001 - mirrors the wrapped call
        items = await original(rule, query)
        seen.extend(
            (item.site, item.external_id)
            for item in items
            if getattr(item, "external_id", None)
        )
        return items

    service._collect = collecting  # type: ignore[attr-defined]
    return seen


async def observe_run(
    session: AsyncSession,
    rule_id: int,
    seen: list[tuple[SiteName, str]] | set[tuple[SiteName, str]],
    *,
    now: datetime | None = None,
) -> ObserveResult:
    """Book one rule run: reset the seen ads, age the missing ones.

    Anything that crossed ``sold_comp_missing_runs`` misses is recorded as sold
    at its last known price.
    """
    result = ObserveResult()
    if not is_enabled():
        return result

    present = {(site, ext) for site, ext in seen if ext}
    if not present:
        # No evidence at all. See the module docstring: silence is ambiguous.
        logger.debug("Rule {}: run saw nothing — sold comparables untouched", rule_id)
        return result
    result.counted = True

    now = now or datetime.now(timezone.utc)
    max_age = timedelta(days=_max_age_days())
    rows = (
        await session.execute(
            select(
                Listing.id, Listing.site, Listing.external_id,
                Listing.price, Listing.created_at,
            ).where(Listing.rule_id == rule_id)
        )
    ).all()
    if not rows:
        return result

    missing_key = MISSING_KEY.format(rule_id=rule_id)
    sold_key = SOLD_KEY.format(rule_id=rule_id)
    ttl = _max_age_days() * 86400

    try:
        async with _redis() as r:
            # An ad already booked as sold must not be booked again, otherwise
            # every later run would refresh its date and an ancient sale would
            # keep counting as today's market.
            already = set(await r.hkeys(sold_key) or [])

            back: list[str] = []
            gone: list[tuple[int, float | None, datetime | None]] = []
            for listing_id, site, external_id, price, created_at in rows:
                if (site, external_id) in present:
                    back.append(str(listing_id))
                elif str(listing_id) not in already:
                    gone.append((listing_id, price, _as_utc(created_at)))

            result.seen = len(back)
            result.missing = len(gone)
            if back:
                await r.hdel(missing_key, *back)

            for listing_id, price, created_at in gone:
                misses = int(await r.hincrby(missing_key, str(listing_id), 1) or 0)
                if misses < _missing_runs():
                    continue
                # Threshold reached: this ad is off the market, whatever the
                # reason — the counter has done its job either way.
                await r.hdel(missing_key, str(listing_id))
                if price is None or price <= 0:
                    continue
                if created_at is not None and now - created_at > max_age:
                    continue
                await r.hset(
                    sold_key,
                    str(listing_id),
                    f"{float(price)}|{int(now.timestamp())}",
                )
                result.sold += 1

            if back or gone:
                await r.expire(missing_key, ttl)
            if result.sold:
                await r.expire(sold_key, ttl)
    except Exception as exc:  # noqa: BLE001 - never break a search run over this
        logger.debug("sold_comps.observe_run failed for rule {}: {}", rule_id, exc)
        return result

    if result.sold:
        logger.info(
            "Rule {}: {} ad(s) disappeared for good — counted as sold",
            rule_id, result.sold,
        )
    return result


# --- Reading the realised prices -------------------------------------------------
async def realised_comps(
    rule_id: int, *, now: datetime | None = None
) -> list[SoldComp]:
    """Realised prices of this rule, newest first, older ones dropped."""
    if not is_enabled():
        return []
    now = now or datetime.now(timezone.utc)
    oldest = now - timedelta(days=_max_age_days())
    try:
        async with _redis() as r:
            raw = await r.hgetall(SOLD_KEY.format(rule_id=rule_id)) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("sold_comps.realised_comps failed for rule {}: {}", rule_id, exc)
        return []

    comps: list[SoldComp] = []
    for field, value in raw.items():
        comp = _parse(field, value)
        if comp is None or comp.sold_at < oldest:
            continue
        comps.append(comp)
    comps.sort(key=lambda c: c.sold_at, reverse=True)
    return comps


async def realised_stats(rule_id: int, *, now: datetime | None = None) -> PriceStats:
    """Price statistics over what actually SOLD under this rule.

    Same shape as the asking-price statistics, so deal scoring can prefer these
    the moment there are enough of them — a realised median is what the item is
    worth, an asking median is what sellers hope for.
    """
    comps = await realised_comps(rule_id, now=now)
    return compute_price_stats([comp.price for comp in comps])


def _parse(field: str, value: str) -> SoldComp | None:
    try:
        price_text, stamp = str(value).split("|", 1)
        return SoldComp(
            listing_id=int(field),
            price=float(price_text),
            sold_at=datetime.fromtimestamp(int(stamp), tz=timezone.utc),
        )
    except (TypeError, ValueError):
        logger.debug("sold_comps: unreadable entry {}={!r}", field, value)
        return None


# --- Periodic housekeeping --------------------------------------------------------
async def prune(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Drop comparables past their age and counters of vanished listings.

    Both keys carry a TTL, but only the whole key: a busy rule keeps refreshing
    it, so single entries would never expire. Retention also deletes listings
    out from under the counters.
    """
    if not is_enabled():
        return 0
    now = now or datetime.now(timezone.utc)
    oldest = now - timedelta(days=_max_age_days())
    removed = 0
    try:
        async with _redis() as r:
            for key in await r.keys("soldcomp:sold:*") or []:
                stale = [
                    field
                    for field, value in (await r.hgetall(key) or {}).items()
                    if (comp := _parse(field, value)) is None or comp.sold_at < oldest
                ]
                if stale:
                    await r.hdel(key, *stale)
                    removed += len(stale)

            for key in await r.keys("soldcomp:missing:*") or []:
                fields = await r.hkeys(key) or []
                ids = {int(f) for f in fields if str(f).isdigit()}
                if not ids:
                    continue
                alive = set(
                    (
                        await session.execute(
                            select(Listing.id).where(Listing.id.in_(ids))
                        )
                    ).scalars().all()
                )
                orphans = [str(i) for i in ids - alive]
                if orphans:
                    await r.hdel(key, *orphans)
                    removed += len(orphans)
    except Exception as exc:  # noqa: BLE001 - housekeeping never breaks a run
        logger.debug("sold_comps.prune failed: {}", exc)
        return removed

    if removed:
        logger.info("Sold comparables: pruned {} stale entry/entries", removed)
    return removed
