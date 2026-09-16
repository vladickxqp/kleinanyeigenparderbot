"""Data retention: keep exactly as much history as the owner's level buys.

Listings, their price points and notification records grow forever. On this
project's own machine that growth already filled a production disk once and
took Postgres down with it, so deleting old rows is not housekeeping — it is
uptime.

How long a row survives is decided by the OWNER's level
(``user.entitlements.history_days``): a paying user keeps their finds and price
charts longer, that is part of what the plan buys. Two kinds of listing are
never deleted, however old they get:

* favourites — the user deliberately kept them, and
* listings a flip references — the purchase record points back at the ad.

The sweep works in bounded batches and commits after every one. A first run on
a table that has grown for months would otherwise delete millions of rows in a
single transaction and hold locks while the live pipeline writes to the same
tables.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import (
    Flip,
    Listing,
    Notification,
    PriceHistory,
    SearchRule,
    SubscriptionTier,
    User,
)
from app.services import entitlements as ent

#: Rows per DELETE statement, and how many batches one sweep may spend in
#: total. Both are read from settings when configured; these are the fallbacks.
DEFAULT_BATCH_SIZE = 500
DEFAULT_MAX_BATCHES = 200

#: Where the sweep publishes its numbers for /status and the heartbeat —
#: same Redis namespace as the counters in :mod:`app.services.health`.
STATS_KEY = "stats:retention"


@dataclass(slots=True)
class RetentionStats:
    """What one sweep removed."""

    listings: int = 0
    price_points: int = 0
    notifications: int = 0
    #: The batch ceiling stopped the sweep before it ran out of old rows, i.e.
    #: the backlog grows faster than one nightly run clears it.
    capped: bool = False

    @property
    def total(self) -> int:
        return self.listings + self.price_points + self.notifications


class _BatchBudget:
    """Ceiling on the delete batches a single sweep may spend."""

    __slots__ = ("left", "capped")

    def __init__(self, batches: int) -> None:
        self.left = batches
        self.capped = False

    def take(self) -> bool:
        if self.left <= 0:
            self.capped = True
            return False
        self.left -= 1
        return True


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


def is_enabled() -> bool:
    """Whether the sweep may delete anything at all."""
    return bool(getattr(settings, "retention_sweep_enabled", True))


def windows() -> dict[int, list[SubscriptionTier]]:
    """Retention window in days -> the stored tier values it applies to.

    Grouping by the resolved number keeps the sweep to one pass per distinct
    window and covers the legacy tier values (they resolve to the level they
    mean) without a second code path.
    """
    grouped: dict[int, list[SubscriptionTier]] = {}
    for tier in SubscriptionTier:
        grouped.setdefault(ent.for_tier(tier).history_days, []).append(tier)
    return grouped


async def sweep(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
    max_batches: int | None = None,
) -> RetentionStats:
    """Delete everything past its owner's retention window.

    Commits after every batch — keeping the lock windows short is the whole
    point of batching, so the caller's transaction is not held open meanwhile.
    """
    stats = RetentionStats()
    if not is_enabled():
        logger.debug("Retention sweep disabled — nothing removed")
        return stats

    now = now or datetime.now(timezone.utc)
    size = batch_size or int(getattr(settings, "retention_batch_size", DEFAULT_BATCH_SIZE))
    budget = _BatchBudget(
        max_batches or int(getattr(settings, "retention_max_batches", DEFAULT_MAX_BATCHES))
    )

    for days, tiers in windows().items():
        if days <= 0:
            # A window of zero would wipe a whole level's history on the next
            # nightly run, and deleted rows do not come back. Refuse instead.
            logger.warning("Retention window of {} day(s) ignored for {}", days, tiers)
            continue
        cutoff = now - timedelta(days=days)
        await _purge_listings(session, tiers, cutoff, size, budget, stats)
        await _purge_notifications(session, tiers, cutoff, size, budget, stats)

    stats.capped = budget.capped
    if stats.total:
        logger.info(
            "Retention sweep: removed {} listing(s), {} price point(s), "
            "{} notification(s){}",
            stats.listings, stats.price_points, stats.notifications,
            " — batch ceiling reached, rest follows next run" if stats.capped else "",
        )
    return stats


async def _purge_listings(
    session: AsyncSession,
    tiers: list[SubscriptionTier],
    cutoff: datetime,
    batch_size: int,
    budget: _BatchBudget,
    stats: RetentionStats,
) -> None:
    """Delete expired listings of these tiers, price history first."""
    # NULL inside a NOT IN subquery makes the whole predicate NULL, which would
    # silently protect every listing. Flips without a listing must be excluded.
    referenced = select(Flip.listing_id).where(Flip.listing_id.is_not(None))
    doomed = (
        select(Listing.id)
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .join(User, User.id == SearchRule.user_id)
        .where(
            User.subscription.in_(tiers),
            Listing.created_at < cutoff,
            Listing.is_favorite.is_(False),
            Listing.id.not_in(referenced),
        )
        .limit(batch_size)
    )
    async for ids in _batches(session, doomed, batch_size, budget):
        # Price points go first: the FK cascade only exists on Postgres, and a
        # counted delete is what makes the sweep's report honest.
        stats.price_points += await _delete(
            session, delete(PriceHistory).where(PriceHistory.listing_id.in_(ids))
        )
        stats.listings += await _delete(
            session, delete(Listing).where(Listing.id.in_(ids))
        )
        await session.commit()


async def _purge_notifications(
    session: AsyncSession,
    tiers: list[SubscriptionTier],
    cutoff: datetime,
    batch_size: int,
    budget: _BatchBudget,
    stats: RetentionStats,
) -> None:
    """Delete delivery records of these tiers past the same window."""
    owners = select(User.id).where(User.subscription.in_(tiers))
    doomed = (
        select(Notification.id)
        .where(Notification.created_at < cutoff, Notification.user_id.in_(owners))
        .limit(batch_size)
    )
    async for ids in _batches(session, doomed, batch_size, budget):
        stats.notifications += await _delete(
            session, delete(Notification).where(Notification.id.in_(ids))
        )
        await session.commit()


async def _batches(
    session: AsyncSession,
    doomed: Select,
    batch_size: int,
    budget: _BatchBudget,
):
    """Yield id batches of ``doomed`` until it runs dry or the budget is spent."""
    while budget.take():
        ids = list((await session.execute(doomed)).scalars().all())
        if not ids:
            return
        yield ids
        if len(ids) < batch_size:
            return


async def _delete(session: AsyncSession, statement) -> int:
    """Run a DELETE and report how many rows it removed."""
    result = await session.execute(
        # The sweep touches rows nobody holds in memory, so skipping the ORM's
        # identity-map synchronisation is both correct and much cheaper.
        statement, execution_options={"synchronize_session": False},
    )
    return int(result.rowcount or 0)


# --- Reporting into the health stats -------------------------------------------
async def record_sweep(stats: RetentionStats) -> None:
    """Publish the sweep's numbers where /status and the heartbeat can read them.

    Fire-and-forget like every other health counter: a Redis outage must not
    turn a successful cleanup into a failed task.
    """
    try:
        async with _redis() as r:
            await r.hset(
                STATS_KEY,
                mapping={
                    "at": int(datetime.now(timezone.utc).timestamp()),
                    "listings": stats.listings,
                    "price_points": stats.price_points,
                    "notifications": stats.notifications,
                    "capped": int(stats.capped),
                },
            )
    except Exception as exc:  # noqa: BLE001 - reporting never breaks the sweep
        logger.debug("retention.record_sweep failed: {}", exc)

    if stats.capped:
        from app.services import health

        await health.report(
            "retention:capped",
            "🧹 <b>Aufräumen kommt nicht hinterher</b>\n"
            f"Der letzte Lauf hat {stats.total} Zeilen gelöscht und dabei sein "
            "Batch-Limit erreicht — es sind noch alte Daten übrig.\n"
            "Bitte Plattenplatz prüfen: <code>df -h</code>",
        )


async def last_sweep() -> dict[str, int] | None:
    """Numbers of the most recent sweep (None = never run / Redis unavailable)."""
    try:
        async with _redis() as r:
            raw = await r.hgetall(STATS_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.debug("retention.last_sweep failed: {}", exc)
        return None
    if not raw:
        return None
    return {key: int(value) for key, value in raw.items()}
