"""Data retention: keep exactly as much history as the owner's level buys.

Listings, their price points and notification records grow forever. On this
project's own machine that growth already filled a production disk once and
took Postgres down with it, so deleting old rows is not housekeeping — it is
uptime.

How long a row survives is decided by the OWNER's level
(``user.entitlements.history_days``): a paying user keeps their finds and price
charts longer, that is part of what the plan buys. A downgrade, however, is
graded: whoever held a higher level less than ``history_grace_days`` ago keeps
that level's window. The tier changes the moment a subscription ends, but a
year of price history cannot be re-fetched from anywhere once it is gone, so
the user gets time to notice, export or come back. Two kinds of listing are
never deleted, however old they get:

* favourites — the user deliberately kept them, and
* listings a flip references — the purchase record points back at the ad.

The sweep works in bounded batches and commits after every one. A first run on
a table that has grown for months would otherwise delete millions of rows in a
single transaction and hold locks while the live pipeline writes to the same
tables. Each category (listings, notifications) gets its OWN row budget: they
used to share one, spent in order, so a large listing backlog meant the
notification table was never reached at all.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import ColumnElement, Select, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import (
    Flip,
    Listing,
    Notification,
    PriceHistory,
    SearchRule,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)
from app.services import entitlements as ent

#: Rows per DELETE statement. The ceiling for a whole sweep comes from
#: ``settings.retention_batch_limit`` and applies per category; this is only
#: how big a single bite is. Both are read from settings when configured.
DEFAULT_BATCH_SIZE = 500
DEFAULT_ROW_LIMIT = 5_000

#: The categories the budget is split between. Price points are not a category
#: of their own: they are deleted with the listing they belong to.
CATEGORY_LISTINGS = "listings"
CATEGORY_NOTIFICATIONS = "notifications"

#: Where the sweep publishes its numbers for /status and the heartbeat —
#: same Redis namespace as the counters in :mod:`app.services.health`.
STATS_KEY = "stats:retention"


@dataclass(slots=True)
class RetentionStats:
    """What one sweep removed, and what it did not get to."""

    listings: int = 0
    price_points: int = 0
    notifications: int = 0
    #: Rows per category the row budget did not reach, counted only for a
    #: category whose own ceiling was spent. Empty = every category ran dry.
    remaining: dict[str, int] = field(default_factory=dict)
    #: Wall-clock seconds the sweep needed.
    elapsed: float = 0.0
    #: False when the kill switch was on — then the zeros mean "did not run",
    #: not "found nothing".
    ran: bool = True

    @property
    def total(self) -> int:
        return self.listings + self.price_points + self.notifications

    @property
    def remaining_total(self) -> int:
        return sum(self.remaining.values())

    @property
    def capped(self) -> bool:
        """The backlog grows faster than one nightly run clears it."""
        return self.remaining_total > 0


@dataclass(slots=True)
class _Cohort:
    """A set of owners that share one retention window."""

    days: int
    owners: ColumnElement[bool]


class _RowBudget:
    """Ceiling on the rows a single sweep may delete in ONE category."""

    __slots__ = ("left",)

    def __init__(self, rows: int) -> None:
        self.left = max(0, rows)

    @property
    def exhausted(self) -> bool:
        return self.left <= 0

    def claim(self, size: int) -> int:
        """Largest batch still allowed — never more than the budget holds."""
        return min(size, self.left)

    def spend(self, rows: int) -> None:
        self.left = max(0, self.left - rows)


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


def window_for_tier(value: object) -> int | None:
    """Window of a stored tier value (None when it names no known level)."""
    if value is None:
        return None
    if isinstance(value, SubscriptionTier):
        return ent.for_tier(value).history_days
    try:
        tier = SubscriptionTier(str(value).strip().lower())
    except ValueError:
        logger.debug("Unknown subscription tier {!r} — no graded window", value)
        return None
    return ent.for_tier(tier).history_days


async def graded_windows(
    session: AsyncSession, now: datetime | None = None
) -> dict[int, int]:
    """Users a downgrade must not punish yet -> the window they keep, in days.

    ``subscriptions`` records when a level ended and which level it was, so the
    highest window a user held recently is recoverable. Only users whose
    remembered window is LONGER than their current one are returned; for
    everybody else the tier window already is the answer.
    """
    grace = int(getattr(settings, "history_grace_days", 0))
    if grace <= 0:
        return {}

    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=grace)
    # No upper bound on the end date on purpose: a cancelled subscription that
    # still runs until the end of its paid period has not ended at all yet.
    ended = (
        await session.execute(
            select(Subscription.user_id, Subscription.tier).where(
                Subscription.status.in_(
                    [SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELED]
                ),
                Subscription.subscription_end >= since,
            )
        )
    ).all()
    if not ended:
        return {}

    held: dict[int, int] = {}
    for user_id, tier_value in ended:
        days = window_for_tier(tier_value)
        if days is None:
            continue
        if days > held.get(user_id, 0):
            held[user_id] = days

    graded: dict[int, int] = {}
    if not held:
        return graded
    current = (
        await session.execute(
            select(User.id, User.subscription).where(User.id.in_(list(held)))
        )
    ).all()
    for user_id, tier in current:
        days = held.get(user_id, 0)
        if days > ent.for_tier(tier).history_days:
            graded[user_id] = days
    if graded:
        logger.info(
            "Retention: {} recently downgraded user(s) keep their longer window",
            len(graded),
        )
    return graded


async def _cohorts(session: AsyncSession, now: datetime) -> list[_Cohort]:
    """Every distinct window plus the owners it applies to, disjointly."""
    graded = await graded_windows(session, now)
    protected = sorted(graded)

    cohorts: list[_Cohort] = []
    for days, tiers in windows().items():
        owners: ColumnElement[bool] = User.subscription.in_(tiers)
        if protected:
            # These users are swept by their graded cohort instead; without the
            # exclusion their own tier's shorter window would delete the rows
            # the grace period is supposed to protect.
            owners = and_(owners, User.id.not_in(protected))
        cohorts.append(_Cohort(days, owners))

    by_window: dict[int, list[int]] = {}
    for user_id, days in graded.items():
        by_window.setdefault(days, []).append(user_id)
    for days, user_ids in by_window.items():
        cohorts.append(_Cohort(days, User.id.in_(user_ids)))
    return cohorts


async def sweep(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
    row_limit: int | None = None,
) -> RetentionStats:
    """Delete everything past its owner's retention window.

    Commits after every batch — keeping the lock windows short is the whole
    point of batching, so the caller's transaction is not held open meanwhile.
    """
    started = time.monotonic()
    stats = RetentionStats()
    if not is_enabled():
        stats.ran = False
        logger.info("Retention sweep is switched off — nothing was removed")
        return stats

    now = now or datetime.now(timezone.utc)
    size = batch_size or int(getattr(settings, "retention_batch_size", DEFAULT_BATCH_SIZE))
    rows = (
        row_limit
        if row_limit is not None
        else int(getattr(settings, "retention_batch_limit", DEFAULT_ROW_LIMIT))
    )
    budgets = {
        CATEGORY_LISTINGS: _RowBudget(rows),
        CATEGORY_NOTIFICATIONS: _RowBudget(rows),
    }

    cohorts = await _cohorts(session, now)
    for cohort in cohorts:
        if cohort.days <= 0:
            # A window of zero would wipe a whole level's history on the next
            # nightly run, and deleted rows do not come back. Refuse instead.
            logger.warning(
                "Retention window of {} day(s) ignored — that would wipe a "
                "whole level's history", cohort.days,
            )
            continue
        cutoff = now - timedelta(days=cohort.days)
        await _purge_listings(
            session, cohort.owners, cutoff, size, budgets[CATEGORY_LISTINGS], stats
        )
        await _purge_notifications(
            session, cohort.owners, cutoff, size, budgets[CATEGORY_NOTIFICATIONS], stats
        )

    stats.remaining = await _remaining(session, cohorts, now, budgets)
    stats.elapsed = time.monotonic() - started
    # Unconditional, zeros included: "ran and found nothing" has to be visible
    # in the log, otherwise it reads exactly like a sweep that never ran.
    logger.info(
        "Retention sweep done in {:.1f}s: removed {} listing(s), {} price "
        "point(s), {} notification(s){}",
        stats.elapsed, stats.listings, stats.price_points, stats.notifications,
        _remaining_note(stats),
    )
    return stats


def _remaining_note(stats: RetentionStats) -> str:
    if not stats.capped:
        return ""
    parts = ", ".join(
        f"{count} {category}" for category, count in sorted(stats.remaining.items()) if count
    )
    return f" — row budget spent, still waiting: {parts}"


# --- Selection ------------------------------------------------------------------
def _doomed_listings(
    owners: ColumnElement[bool], cutoff: datetime, limit: int | None = None
) -> Select:
    """Listings of these owners past ``cutoff`` that nothing protects."""
    # NULL inside a NOT IN subquery makes the whole predicate NULL, which would
    # silently protect every listing. Flips without a listing must be excluded.
    referenced = select(Flip.listing_id).where(Flip.listing_id.is_not(None))
    return (
        select(Listing.id)
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .join(User, User.id == SearchRule.user_id)
        .where(
            owners,
            Listing.created_at < cutoff,
            Listing.is_favorite.is_(False),
            Listing.id.not_in(referenced),
        )
        .limit(limit)
    )


def _doomed_notifications(
    owners: ColumnElement[bool], cutoff: datetime, limit: int | None = None
) -> Select:
    """Delivery records of these owners past ``cutoff``."""
    owner_ids = select(User.id).where(owners)
    return (
        select(Notification.id)
        .where(Notification.created_at < cutoff, Notification.user_id.in_(owner_ids))
        .limit(limit)
    )


#: Which selection belongs to which budget category.
_SELECTORS = {
    CATEGORY_LISTINGS: _doomed_listings,
    CATEGORY_NOTIFICATIONS: _doomed_notifications,
}


async def _remaining(
    session: AsyncSession,
    cohorts: list[_Cohort],
    now: datetime,
    budgets: dict[str, _RowBudget],
) -> dict[str, int]:
    """How much work is left per category, so a backlog is a number not a flag.

    Only counted where the budget actually ran out: a category that emptied its
    selection has nothing left by construction, and COUNT over a grown table is
    not free.
    """
    remaining: dict[str, int] = {}
    for category, budget in budgets.items():
        if not budget.exhausted:
            continue
        selector = _SELECTORS[category]
        total = 0
        for cohort in cohorts:
            if cohort.days <= 0:
                continue
            cutoff = now - timedelta(days=cohort.days)
            total += int(
                await session.scalar(
                    select(func.count()).select_from(
                        selector(cohort.owners, cutoff).subquery()
                    )
                )
                or 0
            )
        remaining[category] = total
    return remaining


# --- Deleting -------------------------------------------------------------------
async def _purge_listings(
    session: AsyncSession,
    owners: ColumnElement[bool],
    cutoff: datetime,
    batch_size: int,
    budget: _RowBudget,
    stats: RetentionStats,
) -> None:
    """Delete these owners' expired listings, price history first."""
    async for ids in _id_batches(
        session, _doomed_listings, owners, cutoff, batch_size, budget
    ):
        # Price points go first: the FK cascade only exists on Postgres, and a
        # counted delete is what makes the sweep's report honest. They ride on
        # the listing budget's back — deleting a listing without its history
        # would leave exactly the orphans this sweep exists to prevent.
        stats.price_points += await _delete(
            session, delete(PriceHistory).where(PriceHistory.listing_id.in_(ids))
        )
        stats.listings += await _delete(
            session, delete(Listing).where(Listing.id.in_(ids))
        )
        await session.commit()


async def _purge_notifications(
    session: AsyncSession,
    owners: ColumnElement[bool],
    cutoff: datetime,
    batch_size: int,
    budget: _RowBudget,
    stats: RetentionStats,
) -> None:
    """Delete these owners' delivery records past the same window."""
    async for ids in _id_batches(
        session, _doomed_notifications, owners, cutoff, batch_size, budget
    ):
        stats.notifications += await _delete(
            session, delete(Notification).where(Notification.id.in_(ids))
        )
        await session.commit()


async def _id_batches(
    session: AsyncSession,
    selector,
    owners: ColumnElement[bool],
    cutoff: datetime,
    batch_size: int,
    budget: _RowBudget,
):
    """Yield id batches until the selection runs dry or the budget is spent."""
    while not budget.exhausted:
        limit = budget.claim(batch_size)
        ids = list(
            (await session.execute(selector(owners, cutoff, limit))).scalars().all()
        )
        if not ids:
            return
        budget.spend(len(ids))
        yield ids
        if len(ids) < limit:
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
                    "remaining_listings": stats.remaining.get(CATEGORY_LISTINGS, 0),
                    "remaining_notifications": stats.remaining.get(
                        CATEGORY_NOTIFICATIONS, 0
                    ),
                    "elapsed_ms": int(stats.elapsed * 1000),
                    # A crash recorded earlier must not haunt a healthy sweep.
                    "ok": 1,
                    "error": "",
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
            "Zeilen-Limit erreicht. Es warten noch "
            f"{stats.remaining.get(CATEGORY_LISTINGS, 0)} Angebote und "
            f"{stats.remaining.get(CATEGORY_NOTIFICATIONS, 0)} Benachrichtigungen.\n"
            "Bitte Plattenplatz prüfen: <code>df -h</code>",
        )


async def record_sweep_failure(exc: BaseException, *, elapsed: float = 0.0) -> None:
    """Remember that the cleanup crashed.

    A sweep that raised used to write nothing at all, so from the outside it
    looked exactly like a night with nothing to delete — until the disk was
    full again.
    """
    detail = f"{type(exc).__name__}: {exc}"[:200]
    try:
        async with _redis() as r:
            await r.hset(
                STATS_KEY,
                mapping={
                    # "at" stays untouched: it means LAST SUCCESS, and that is
                    # what the staleness check needs.
                    "ok": 0,
                    "failed_at": int(datetime.now(timezone.utc).timestamp()),
                    "error": detail,
                    "elapsed_ms": int(elapsed * 1000),
                },
            )
    except Exception as redis_exc:  # noqa: BLE001
        logger.debug("retention.record_sweep_failure failed: {}", redis_exc)

    from app.services import health

    await health.report(
        "retention:failed",
        "🧹 <b>Aufräumen ist fehlgeschlagen</b>\n"
        f"Der nächtliche Lauf ist abgebrochen: <code>{detail}</code>\n"
        "Ohne Aufräumen wächst die Datenbank weiter — bitte Logs prüfen: "
        "<code>docker compose logs worker</code>",
    )


async def last_sweep() -> dict[str, int | str] | None:
    """Numbers of the most recent sweep (None = never run / Redis unavailable)."""
    try:
        async with _redis() as r:
            raw = await r.hgetall(STATS_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.debug("retention.last_sweep failed: {}", exc)
        return None
    if not raw:
        return None
    parsed: dict[str, int | str] = {}
    for key, value in raw.items():
        try:
            parsed[key] = int(value)
        except (TypeError, ValueError):
            parsed[key] = value
    return parsed
