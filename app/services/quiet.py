"""Quiet hours and the morning digest.

Users can define a nightly window (e.g. 22:00–07:00) during which the bot does
not ping them. Deal cards that would fire inside the window are queued in Redis
instead; a worker beat task flushes the queue as a "good morning" digest once
the window ends.

Storage lives in Redis (``quiet:cfg:<tg_id>``, ``digest:<tg_id>``) — no schema
migration required, and the config survives restarts thanks to AOF persistence.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from app.services.health import _redis

#: Maximum number of cards delivered with one digest; the rest is summarised.
DIGEST_MAX_CARDS = 8


def is_in_window(hour: int, start: int, end: int) -> bool:
    """True if ``hour`` lies inside the [start, end) window (may wrap midnight)."""
    if start == end:
        return False  # zero-length window = disabled
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight, e.g. 22 -> 7


# --- Configuration ---------------------------------------------------------------
async def set_quiet(telegram_id: int, start: int | None, end: int | None) -> None:
    """Set (or with ``None`` disable) a user's quiet window."""
    try:
        async with _redis() as r:
            key = f"quiet:cfg:{telegram_id}"
            if start is None or end is None:
                await r.delete(key)
            else:
                await r.set(key, f"{int(start)}:{int(end)}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("quiet.set_quiet failed: {}", exc)


async def get_quiet(telegram_id: int) -> tuple[int, int] | None:
    """Return the user's (start_hour, end_hour) window, or None if disabled."""
    try:
        async with _redis() as r:
            raw = await r.get(f"quiet:cfg:{telegram_id}")
        if raw:
            start, end = raw.split(":")
            return int(start), int(end)
    except Exception as exc:  # noqa: BLE001
        logger.debug("quiet.get_quiet failed: {}", exc)
    return None


async def is_quiet_now(telegram_id: int, now: datetime | None = None) -> bool:
    """True if the user is currently inside their quiet window."""
    window = await get_quiet(telegram_id)
    if window is None:
        return False
    now = now or datetime.now()  # container runs in the user's TZ
    return is_in_window(now.hour, window[0], window[1])


# --- Digest queue ------------------------------------------------------------------
async def queue_digest(telegram_id: int, listing_ids: list[int]) -> None:
    """Defer listing notifications into the user's digest queue."""
    if not listing_ids:
        return
    try:
        async with _redis() as r:
            await r.rpush(f"digest:{telegram_id}", *[str(i) for i in listing_ids])
            await r.expire(f"digest:{telegram_id}", 3 * 86400)
        logger.info(
            "Quiet hours: deferred {} card(s) for {}", len(listing_ids), telegram_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("quiet.queue_digest failed: {}", exc)


async def pop_digest(telegram_id: int, limit: int = 100) -> list[int]:
    """Drain the user's digest queue (deduplicated, order preserved)."""
    ids: list[int] = []
    try:
        async with _redis() as r:
            key = f"digest:{telegram_id}"
            for _ in range(limit):
                raw = await r.lpop(key)
                if raw is None:
                    break
                ids.append(int(raw))
    except Exception as exc:  # noqa: BLE001
        logger.debug("quiet.pop_digest failed: {}", exc)
    return list(dict.fromkeys(ids))


async def digest_size(telegram_id: int) -> int:
    """Number of currently queued digest items for a user."""
    try:
        async with _redis() as r:
            return int(await r.llen(f"digest:{telegram_id}") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("quiet.digest_size failed: {}", exc)
        return 0


async def users_with_pending_digest() -> list[int]:
    """Telegram ids that currently have queued digest items."""
    users: list[int] = []
    try:
        async with _redis() as r:
            async for key in r.scan_iter(match="digest:*", count=100):
                try:
                    users.append(int(str(key).rsplit(":", 1)[-1]))
                except ValueError:
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.debug("quiet.users_with_pending_digest failed: {}", exc)
    return users
