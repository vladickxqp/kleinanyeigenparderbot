"""Health tracking and admin alerting.

Silent failures are the worst failure mode for a deal bot: parsers break, sites
start blocking, locations stop resolving — and the user just receives nothing.
This module records such events in Redis and queues one-off alert messages that
the worker delivers to the bot admins (``BOT_ADMIN_IDS``).

Every function here is fire-and-forget: any Redis/network problem is swallowed
(and logged at debug level) so health reporting can never break the pipeline.
"""

from __future__ import annotations

from loguru import logger

from app.config.settings import settings

#: Redis list holding queued alert messages for the admins.
ALERT_QUEUE = "health:alerts"
#: A parser is reported after this many consecutive failures.
FAIL_THRESHOLD = 3
#: Default dedup window: the same alert key fires at most once per 6 hours.
DEDUP_TTL_SECONDS = 6 * 3600

_client = None


def _get_client():
    """Lazily create a shared async Redis client."""
    global _client
    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def report(key: str, message: str, dedup_ttl: int = DEDUP_TTL_SECONDS) -> None:
    """Queue an admin alert, at most once per ``key`` per dedup window."""
    try:
        r = _get_client()
        if await r.set(f"health:sent:{key}", "1", nx=True, ex=dedup_ttl):
            await r.rpush(ALERT_QUEUE, message)
            logger.info("Health alert queued ({}): {}", key, message)
    except Exception as exc:  # noqa: BLE001 - alerting must never break anything
        logger.debug("health.report failed: {}", exc)


async def record_parser_result(site: str, ok: bool) -> None:
    """Track consecutive parser failures; alert once the threshold is hit."""
    try:
        r = _get_client()
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
        r = _get_client()
        for _ in range(limit):
            msg = await r.lpop(ALERT_QUEUE)
            if msg is None:
                break
            messages.append(msg)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.pop_alerts failed: {}", exc)
    return messages
