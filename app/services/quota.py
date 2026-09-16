"""Usage metering: daily and monthly counters per user, enforced against the
user's entitlements.

Counters live in Redis with a TTL matching their window, using the same
short-lived-connection pattern as :mod:`app.services.health` (the worker runs
every task in its own event loop). Every check fails OPEN: if Redis is down the
action is allowed, because a metering outage must never silence the product.

Two operations only:

* :func:`check` — how much is left, without consuming anything.
* :func:`consume` — atomically take one unit; tells the caller whether the cap
  was already reached so it can show the named "you would have seen X" teaser
  instead of quietly dropping the action.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger

from app.config.settings import settings
from app.database.models import User
from app.services import entitlements as ent

#: Quota kinds and the entitlement field that caps them.
KIND_CARDS = "cards"                 # deal cards delivered, per day
KIND_PHOTO = "photo"                 # photo valuations, per month
KIND_PHOTO_DAY = "photo_day"         # fair-use brake for unlimited plans
KIND_QUICK = "quick"                 # /suche, per day
KIND_NEGO = "nego"                   # negotiation assistant, per month

_WINDOW: dict[str, str] = {
    KIND_CARDS: "day",
    KIND_PHOTO: "month",
    KIND_PHOTO_DAY: "day",
    KIND_QUICK: "day",
    KIND_NEGO: "month",
}


@asynccontextmanager
async def _redis():
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


def _stamp(window: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%d") if window == "day" else now.strftime("%Y%m")


def _ttl(window: str) -> int:
    return 2 * 86400 if window == "day" else 35 * 86400


def _key(kind: str, telegram_id: int, now: datetime | None = None) -> str:
    return f"quota:{kind}:{telegram_id}:{_stamp(_WINDOW[kind], now)}"


def limit_for(kind: str, user: User) -> int:
    """The cap for this kind of action under the user's current level."""
    e = ent.for_tier(user.subscription)
    if kind == KIND_CARDS:
        return e.daily_notifications
    if kind == KIND_PHOTO:
        return e.photo_evals_per_month
    if kind == KIND_PHOTO_DAY:
        return settings.photo_evals_fair_use_per_day
    if kind == KIND_QUICK:
        return e.quick_searches_per_day
    if kind == KIND_NEGO:
        return e.negotiations_per_month
    return ent.UNLIMITED


def _exempt(user: User) -> bool:
    return user.telegram_id in settings.admin_ids


@dataclass(frozen=True, slots=True)
class QuotaState:
    kind: str
    used: int
    limit: int          # -1 = unlimited

    @property
    def unlimited(self) -> bool:
        return ent.is_unlimited(self.limit)

    @property
    def remaining(self) -> int:
        return ent.UNLIMITED if self.unlimited else max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return not self.unlimited and self.used >= self.limit

    @property
    def window_label(self) -> str:
        return "heute" if _WINDOW[self.kind] == "day" else "diesen Monat"


async def check(kind: str, user: User, now: datetime | None = None) -> QuotaState:
    """Current usage without consuming."""
    limit = ent.UNLIMITED if _exempt(user) else limit_for(kind, user)
    used = 0
    try:
        async with _redis() as r:
            used = int(await r.get(_key(kind, user.telegram_id, now)) or 0)
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("quota.check({}) unavailable: {}", kind, exc)
    return QuotaState(kind=kind, used=used, limit=limit)


async def consume(
    kind: str, user: User, *, amount: int = 1, now: datetime | None = None
) -> QuotaState:
    """Take ``amount`` units. The returned state is AFTER consumption.

    When the cap is already reached nothing is consumed and ``exhausted`` is
    True, so the caller can explain instead of silently dropping the action.
    """
    limit = ent.UNLIMITED if _exempt(user) else limit_for(kind, user)
    key = _key(kind, user.telegram_id, now)
    try:
        async with _redis() as r:
            used = int(await r.get(key) or 0)
            if not ent.is_unlimited(limit) and used + amount > limit:
                return QuotaState(kind=kind, used=used, limit=limit)
            used = int(await r.incrby(key, amount))
            if used == amount:
                await r.expire(key, _ttl(_WINDOW[kind]))
            return QuotaState(kind=kind, used=used, limit=limit)
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("quota.consume({}) unavailable: {}", kind, exc)
        return QuotaState(kind=kind, used=0, limit=limit)


async def release(kind: str, user: User, *, amount: int = 1) -> None:
    """Give a unit back (e.g. the photo could not be analysed after all)."""
    try:
        async with _redis() as r:
            key = _key(kind, user.telegram_id)
            if int(await r.get(key) or 0) >= amount:
                await r.decrby(key, amount)
    except Exception as exc:  # noqa: BLE001
        logger.debug("quota.release({}) unavailable: {}", kind, exc)


async def snapshot(user: User) -> dict[str, QuotaState]:
    """Every metered kind at once — for /usage and the Mini App."""
    kinds = (KIND_CARDS, KIND_PHOTO, KIND_QUICK, KIND_NEGO)
    return {kind: await check(kind, user) for kind in kinds}


def upgrade_hint(kind: str, user: User) -> str | None:
    """What the next level would give for this kind of action (HTML)."""
    nxt = ent.next_tier(user.subscription)
    if nxt is None:
        return None
    e = ent.for_tier(nxt)
    value = {
        KIND_CARDS: ent.fmt_quota(e.daily_notifications, " Karten/Tag"),
        KIND_PHOTO: ent.fmt_quota(e.photo_evals_per_month, " Foto-Bewertungen/Monat"),
        KIND_QUICK: ent.fmt_quota(e.quick_searches_per_day, " Schnell-Suchen/Tag"),
        KIND_NEGO: ent.fmt_quota(e.negotiations_per_month, " Verhandlungen/Monat"),
    }.get(kind)
    if value is None:
        return None
    return f"<b>{e.label}</b>: {value} — /premium"
