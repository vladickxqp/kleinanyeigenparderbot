"""Health tracking, activity statistics and admin alerting.

Silent failures are the worst failure mode for a deal bot: parsers break, sites
start blocking, locations stop resolving — and the user just receives nothing.
This module records such events plus activity counters in Redis. Queued alerts
are delivered to the bot admins (``BOT_ADMIN_IDS``) by a worker beat task, and
the counters power ``/status`` and the daily heartbeat.

Every function here is fire-and-forget: any Redis/network problem is swallowed
(and logged at debug level) so health reporting can never break the pipeline.

Note on connections: the Celery worker wraps every task in its own
``asyncio.run`` loop, so a cached client would be bound to a dead loop after
the first task. Each operation therefore opens a short-lived connection.
"""

from __future__ import annotations

import time as _time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from loguru import logger

from app.config.settings import settings

#: Redis list holding queued alert messages for the admins.
ALERT_QUEUE = "health:alerts"
#: A parser is reported after this many consecutive failures.
FAIL_THRESHOLD = 3
#: Default dedup window: the same alert key fires at most once per 6 hours.
DEDUP_TTL_SECONDS = 6 * 3600
#: The retention sweep runs nightly. Missing one run can be a reboot; missing
#: a day and a half means it is broken, and an unswept database once filled
#: this project's production disk.
SWEEP_MAX_AGE_SECONDS = 36 * 3600


@asynccontextmanager
async def _redis():
    """Short-lived Redis connection, safe across independent event loops."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


async def report(key: str, message: str, dedup_ttl: int = DEDUP_TTL_SECONDS) -> None:
    """Queue an admin alert, at most once per ``key`` per dedup window."""
    try:
        async with _redis() as r:
            if await r.set(f"health:sent:{key}", "1", nx=True, ex=dedup_ttl):
                await r.rpush(ALERT_QUEUE, message)
                logger.info("Health alert queued ({}): {}", key, message)
    except Exception as exc:  # noqa: BLE001 - alerting must never break anything
        logger.debug("health.report failed: {}", exc)


async def record_parser_result(site: str, ok: bool) -> None:
    """Track consecutive parser failures; alert once the threshold is hit.

    On the threshold the dispatcher is also told to back off: every interval
    is widened for a while, because a ban would hit exactly the paying users
    who were sold speed.
    """
    try:
        async with _redis() as r:
            fail_key = f"health:fail:{site}"
            if ok:
                await r.delete(fail_key)
                await r.delete(f"health:sent:parser:{site}")
                return
            count = await r.incr(fail_key)
            await r.expire(fail_key, 3600)
        if count == FAIL_THRESHOLD:
            await start_block_backoff(site)
            await report(
                f"parser:{site}",
                f"⚠️ Parser <b>{site}</b> ist {FAIL_THRESHOLD}× in Folge "
                "fehlgeschlagen.\nMögliche Ursachen: Seite blockiert den Bot, "
                "Layout geändert, Netzwerkproblem. Alle Intervalle wurden "
                f"vorübergehend ×{settings.block_backoff_multiplier:g} gestreckt. "
                "Details: <code>docker compose logs worker</code>",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.record_parser_result failed: {}", exc)


async def start_block_backoff(site: str) -> None:
    """Widen every interval for a while after a suspected block."""
    if not settings.block_backoff_enabled:
        return
    try:
        async with _redis() as r:
            await r.set(f"health:backoff:{site}", "1", ex=settings.block_backoff_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.start_block_backoff failed: {}", exc)


async def block_multiplier() -> float:
    """Interval multiplier the dispatcher applies (1.0 = normal operation)."""
    if not settings.block_backoff_enabled:
        return 1.0
    try:
        async with _redis() as r:
            keys = await r.keys("health:backoff:*")
            return settings.block_backoff_multiplier if keys else 1.0
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.block_multiplier failed: {}", exc)
        return 1.0


async def pop_alerts(limit: int = 10) -> list[str]:
    """Drain up to ``limit`` queued alert messages (used by the worker)."""
    messages: list[str] = []
    try:
        async with _redis() as r:
            for _ in range(limit):
                msg = await r.lpop(ALERT_QUEUE)
                if msg is None:
                    break
                messages.append(msg)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.pop_alerts failed: {}", exc)
    return messages


# --- Activity statistics (for /status and the daily heartbeat) -----------------
def _today() -> str:
    return _time.strftime("%Y%m%d")


async def mark_dispatch() -> None:
    """Record that the beat dispatcher just ran (worker liveness signal)."""
    try:
        async with _redis() as r:
            await r.set("stats:last_dispatch", _time.time())
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.mark_dispatch failed: {}", exc)


async def record_rule_run() -> None:
    """Count one executed search run for today."""
    try:
        async with _redis() as r:
            key = f"stats:runs:{_today()}"
            await r.incr(key)
            await r.expire(key, 3 * 86400)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.record_rule_run failed: {}", exc)


async def record_card_sent() -> None:
    """Count one delivered deal card for today."""
    try:
        async with _redis() as r:
            key = f"stats:sent:{_today()}"
            await r.incr(key)
            await r.expire(key, 3 * 86400)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.record_card_sent failed: {}", exc)


async def queue_depth(queue: str = "celery") -> int | None:
    """How many tasks are waiting in the Celery queue (None if unknown)."""
    try:
        async with _redis() as r:
            return int(await r.llen(queue))
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.queue_depth failed: {}", exc)
        return None


@dataclass(slots=True)
class StatusSnapshot:
    """Current operational status, for /status and the heartbeat."""

    worker_alive: bool
    last_dispatch_age: float | None   # seconds; None = never seen
    runs_today: int
    cards_sent_today: int
    # --- Nightly retention sweep (see app.services.retention) --------------
    #: Seconds since the last SUCCESSFUL sweep; None = never succeeded.
    sweep_age: float | None = None
    sweep_listings: int = 0
    sweep_price_points: int = 0
    sweep_notifications: int = 0
    #: Rows the sweep's row budget did not reach, across all categories.
    sweep_remaining: int = 0
    sweep_failed: bool = False
    sweep_error: str | None = None

    @property
    def sweep_ran(self) -> bool:
        """A sweep that found nothing still ran — the two must not look alike."""
        return self.sweep_age is not None

    @property
    def sweep_stale(self) -> bool:
        return self.sweep_age is None or self.sweep_age > SWEEP_MAX_AGE_SECONDS

    @property
    def sweep_line(self) -> str:
        """One line about the cleanup, for /status and the heartbeat."""
        if self.sweep_failed:
            detail = f": <code>{self.sweep_error}</code>" if self.sweep_error else ""
            return f"🔴 Aufräumen: letzter Lauf fehlgeschlagen{detail}"
        if self.sweep_age is None:
            return "🔴 Aufräumen: lief noch nie"
        removed = (
            f"{self.sweep_listings} Angebote, {self.sweep_price_points} Preispunkte, "
            f"{self.sweep_notifications} Meldungen"
        )
        age = _age_text(self.sweep_age)
        icon = "🟠" if self.sweep_stale else "🧹"
        rest = f" · {self.sweep_remaining} Zeilen offen" if self.sweep_remaining else ""
        return f"{icon} Aufräumen: {age} — {removed} gelöscht{rest}"


def _age_text(seconds: float) -> str:
    """German, informal age of an event ("vor 3 h")."""
    if seconds < 3600:
        return f"vor {int(seconds // 60)} min"
    if seconds < 86400:
        return f"vor {int(seconds // 3600)} h"
    return f"vor {int(seconds // 86400)} Tag(en)"


def _as_int(raw: dict[str, str], key: str) -> int:
    try:
        return int(raw.get(key) or 0)
    except (TypeError, ValueError):
        return 0


async def get_status() -> StatusSnapshot:
    """Read the activity counters. Degrades to 'unknown' on Redis errors."""
    # The sweep's own key, so /status and the heartbeat report the cleanup
    # instead of nobody ever reading the numbers it writes. Imported late:
    # retention pulls in the ORM models, which the bot does not need for this.
    from app.services.retention import STATS_KEY as SWEEP_KEY

    last_age: float | None = None
    runs = 0
    sent = 0
    sweep: dict[str, str] = {}
    try:
        async with _redis() as r:
            raw = await r.get("stats:last_dispatch")
            if raw is not None:
                last_age = max(0.0, _time.time() - float(raw))
            runs = int(await r.get(f"stats:runs:{_today()}") or 0)
            sent = int(await r.get(f"stats:sent:{_today()}") or 0)
            sweep = await r.hgetall(SWEEP_KEY) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.get_status failed: {}", exc)
    # The dispatcher fires every 20s; anything under 2 minutes counts as alive.
    alive = last_age is not None and last_age < 120

    sweep_at = _as_int(sweep, "at")
    return StatusSnapshot(
        worker_alive=alive,
        last_dispatch_age=last_age,
        runs_today=runs,
        cards_sent_today=sent,
        sweep_age=max(0.0, _time.time() - sweep_at) if sweep_at else None,
        sweep_listings=_as_int(sweep, "listings"),
        sweep_price_points=_as_int(sweep, "price_points"),
        sweep_notifications=_as_int(sweep, "notifications"),
        sweep_remaining=(
            _as_int(sweep, "remaining_listings")
            + _as_int(sweep, "remaining_notifications")
        ),
        sweep_failed=bool(sweep) and _as_int(sweep, "ok") == 0,
        sweep_error=(sweep.get("error") or None),
    )


async def check_sweep(status: StatusSnapshot | None = None) -> str | None:
    """Alert the admins when the nightly cleanup failed or stopped succeeding.

    Numbers that only exist in Redis are numbers nobody reads: the disk filled
    up once because a broken sweep is as quiet as a sweep with nothing to do.
    Returns the finding so the caller can show it too, None when all is well.
    """
    status = status or await get_status()

    if status.sweep_failed:
        detail = f": <code>{status.sweep_error}</code>" if status.sweep_error else ""
        finding = f"🧹 Letztes Aufräumen ist fehlgeschlagen{detail}"
        await report(
            "retention:failed",
            f"{finding}\nOhne Aufräumen wächst die Datenbank weiter — "
            "Logs prüfen: <code>docker compose logs worker</code>",
        )
        return finding

    if status.sweep_age is None:
        finding = "🧹 Das Aufräumen lief noch nie erfolgreich"
        # Once a day is enough for a state that only changes at 03:30.
        await report(
            "retention:never",
            f"{finding} — läuft der Beat-Zeitplan? "
            "<code>docker compose logs beat</code>",
            dedup_ttl=24 * 3600,
        )
        return finding

    if status.sweep_age > SWEEP_MAX_AGE_SECONDS:
        hours = int(status.sweep_age // 3600)
        finding = f"🧹 Seit {hours} h kein erfolgreiches Aufräumen"
        await report(
            "retention:stale",
            f"{finding} (normal: jede Nacht).\n"
            "Die Datenbank wächst währenddessen weiter: "
            "<code>docker compose logs worker</code>",
        )
        return finding

    return None
