"""Redis-backed rate limits and locks that hold across processes.

In-process counters are not enough here: the worker runs several OS processes
and the bot is a separate container, so anything that protects a shared
resource (the marketplaces we scrape, a single rule's execution, a user's
command budget) has to live in Redis.

Every helper fails OPEN: if Redis is unreachable the action is allowed rather
than the whole bot going silent. Losing a rate limit for a few minutes is far
cheaper than refusing every command.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from loguru import logger

from app.config.settings import settings

#: Manual "run now" per user.
MANUAL_RUN_COOLDOWN = 60
#: Generic per-user command budget.
COMMAND_LIMIT = 20
COMMAND_WINDOW = 60


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


async def cooldown(key: str, seconds: int) -> int:
    """Start a cooldown. Returns 0 if it was free, else the seconds left."""
    try:
        async with _redis() as r:
            if await r.set(f"cd:{key}", "1", nx=True, ex=seconds):
                return 0
            ttl = await r.ttl(f"cd:{key}")
            return max(int(ttl), 1)
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("Cooldown check failed for {}: {}", key, exc)
        return 0


async def manual_run_allowed(
    telegram_id: int, seconds: int | None = None, scope: str = "manual"
) -> int:
    """0 if a manual search may start now, else the seconds to wait.

    ``scope`` separates the counters: the quick search and the in-chat "run now"
    button have different cooldowns, so sharing one key would make each of them
    report the other's wait time.
    """
    return await cooldown(f"{scope}:{telegram_id}", seconds or MANUAL_RUN_COOLDOWN)


async def rate_limited(
    key: str, limit: int = COMMAND_LIMIT, window: int = COMMAND_WINDOW
) -> bool:
    """True when ``key`` has used up its budget in the current window."""
    try:
        async with _redis() as r:
            bucket = f"rl:{key}"
            count = await r.incr(bucket)
            if count == 1:
                await r.expire(bucket, window)
            return count > limit
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("Rate limit check failed for {}: {}", key, exc)
        return False


@asynccontextmanager
async def rule_lock(rule_id: int, ttl: int = 300):
    """Guard one rule against overlapping runs across all worker processes.

    Yields True when the lock was acquired. A long-running scrape must not be
    started a second time by the next dispatcher tick: both runs would read the
    same "already known" fingerprints and insert duplicate rows.
    """
    key = f"lock:rule:{rule_id}"
    acquired = False
    client = None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        acquired = bool(await client.set(key, "1", nx=True, ex=ttl))
    except Exception as exc:  # noqa: BLE001 - fail open, better a duplicate than a stall
        logger.debug("Rule lock unavailable for {}: {}", rule_id, exc)
        acquired = True
        client = None
    try:
        yield acquired
    finally:
        if client is not None:
            try:
                if acquired:
                    await client.delete(key)
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass


async def site_slot_wait(site: str, min_delay: float, egress: str = "direct") -> float:
    """Seconds this process must wait before hitting ``site`` again.

    Fleet-wide pacing: the token lives in Redis, so several worker processes
    scraping in parallel respect one shared delay instead of a multiple of the
    configured request rate.

    The token is per EXIT ADDRESS, not per marketplace. A marketplace rate-limits
    the address it sees, so one shared token across all proxies would cap the
    whole fleet at a single address's budget and make buying proxies pointless.
    """
    if min_delay <= 0:
        return 0.0
    try:
        async with _redis() as r:
            key = f"pace:{site}:{egress}"
            px = max(int(min_delay * 1000), 1)
            if await r.set(key, "1", nx=True, px=px):
                return 0.0
            ttl_ms = await r.pttl(key)
            return max(ttl_ms, 0) / 1000.0
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("Site pacing unavailable for {}/{}: {}", site, egress, exc)
        return 0.0


async def pick_egress(site: str, candidates: list[str], min_delay: float) -> tuple[str, float]:
    """Choose the exit address that can hit ``site`` soonest.

    With a pool, picking at random makes the fleet wait on a busy address while
    an idle one sits unused. Returns the chosen address and how long it still
    has to wait; the caller sleeps that long and then makes the request.
    """
    best: tuple[str, float] | None = None
    for candidate in candidates:
        wait = await site_slot_wait(site, min_delay, candidate)
        if wait <= 0:
            return candidate, 0.0
        if best is None or wait < best[1]:
            best = (candidate, wait)
    return best or ("direct", 0.0)
