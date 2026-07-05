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
    """Track consecutive parser failures; alert once the threshold is hit."""
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
            await report(
                f"parser:{site}",
                f"⚠️ Parser <b>{site}</b> ist {FAIL_THRESHOLD}× in Folge "
                "fehlgeschlagen.\nMögliche Ursachen: Seite blockiert den Bot, "
                "Layout geändert, Netzwerkproblem. Details: "
                "<code>docker compose logs worker</code>",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.record_parser_result failed: {}", exc)


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


@dataclass(slots=True)
class StatusSnapshot:
    """Current operational status, for /status and the heartbeat."""

    worker_alive: bool
    last_dispatch_age: float | None   # seconds; None = never seen
    runs_today: int
    cards_sent_today: int


async def get_status() -> StatusSnapshot:
    """Read the activity counters. Degrades to 'unknown' on Redis errors."""
    last_age: float | None = None
    runs = 0
    sent = 0
    try:
        async with _redis() as r:
            raw = await r.get("stats:last_dispatch")
            if raw is not None:
                last_age = max(0.0, _time.time() - float(raw))
            runs = int(await r.get(f"stats:runs:{_today()}") or 0)
            sent = int(await r.get(f"stats:sent:{_today()}") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.get_status failed: {}", exc)
    # The dispatcher fires every 20s; anything under 2 minutes counts as alive.
    alive = last_age is not None and last_age < 120
    return StatusSnapshot(
        worker_alive=alive,
        last_dispatch_age=last_age,
        runs_today=runs,
        cards_sent_today=sent,
    )
