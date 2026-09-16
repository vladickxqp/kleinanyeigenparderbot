"""Usage metering: daily and monthly counters per user, enforced against the
user's entitlements.

Counters live in Redis with a TTL matching their window, using the same
short-lived-connection pattern as :mod:`app.services.health` (the worker runs
every task in its own event loop). Every check fails OPEN: if Redis is down the
action is allowed, because a metering outage must never silence the product.

Three operations only:

* :func:`check` — how much is left, without consuming anything.
* :func:`consume` — atomically take one unit; tells the caller whether the cap
  was already reached so it can show the named "you would have seen X" teaser
  instead of quietly dropping the action.
* :func:`release` — hand a unit back when the action failed after booking.

A booking and its refund can land in different windows: a photo booked at
23:59:58 whose analysis fails at 00:00:03 would decrement the fresh day and
leave yesterday inflated for the rest of its TTL. Every :class:`QuotaState`
therefore carries the ``stamp`` of the window it touched, which :func:`release`
accepts; and :func:`consume` additionally parks that stamp in Redis, so even a
caller that kept nothing (``release(kind, user)``) still refunds the window the
last booking came from.
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

    # Explicit timeouts: without them "fails open" only covers a refused
    # connection. A blackholed host would block the handler instead, which is
    # the one failure mode metering must never cause.
    client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
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


def _key_for(kind: str, telegram_id: int, stamp: str) -> str:
    return f"quota:{kind}:{telegram_id}:{stamp}"


def _key(kind: str, telegram_id: int, now: datetime | None = None) -> str:
    return _key_for(kind, telegram_id, _stamp(_WINDOW[kind], now))


def _booked_key(kind: str, telegram_id: int) -> str:
    """Where :func:`consume` parks the window it booked from.

    It is what makes a stamp-less ``release()`` land in the right window, so
    call sites that do not carry the :class:`QuotaState` around are correct
    without changing them.
    """
    return f"quota:booked:{kind}:{telegram_id}"


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
    #: Window this state was read from / booked in ("20260916" or "202609").
    #: Hand it back to :func:`release` to refund exactly that window.
    stamp: str = ""
    #: False when Redis was unavailable and the action was NOT counted. Callers
    #: decide a refusal by comparing counters, and a fail-open state has a
    #: counter that did not move — indistinguishable from "the cap refused me"
    #: unless they can see that nothing was metered at all.
    metered: bool = True

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
    def is_daily(self) -> bool:
        return _WINDOW[self.kind] == "day"

    def window_label(self, lang: str | None = None) -> str:
        """"today" / "this month" in the reader's language.

        This used to be a German-only property, and every caller dropped it
        verbatim into an otherwise translated sentence.
        """
        from app.bot.texts import t

        return t("quota.window_day" if self.is_daily else "quota.window_month", lang)


async def check(kind: str, user: User, now: datetime | None = None) -> QuotaState:
    """Current usage without consuming."""
    limit = ent.UNLIMITED if _exempt(user) else limit_for(kind, user)
    stamp = _stamp(_WINDOW[kind], now)
    try:
        async with _redis() as r:
            used = int(await r.get(_key_for(kind, user.telegram_id, stamp)) or 0)
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("quota.check({}) unavailable: {}", kind, exc)
        return QuotaState(kind=kind, used=0, limit=limit, stamp=stamp, metered=False)
    return QuotaState(kind=kind, used=used, limit=limit, stamp=stamp)


async def consume(
    kind: str, user: User, *, amount: int = 1, now: datetime | None = None
) -> QuotaState:
    """Take ``amount`` units. The returned state is AFTER consumption.

    When the cap is already reached nothing is consumed and ``exhausted`` is
    True, so the caller can explain instead of silently dropping the action.

    The returned ``stamp`` names the window the unit came from — pass it to
    :func:`release` and a refund can never hit the wrong side of midnight.
    """
    limit = ent.UNLIMITED if _exempt(user) else limit_for(kind, user)
    window = _WINDOW[kind]
    stamp = _stamp(window, now)
    key = _key_for(kind, user.telegram_id, stamp)
    try:
        async with _redis() as r:
            used = int(await r.get(key) or 0)
            if not ent.is_unlimited(limit) and used + amount > limit:
                return QuotaState(kind=kind, used=used, limit=limit, stamp=stamp)
            used = int(await r.incrby(key, amount))
            if used == amount:
                await r.expire(key, _ttl(window))
            # Park the window so a refund that arrives in the NEXT one still
            # knows where the unit came from, even from a call site that keeps
            # no state.
            await r.set(_booked_key(kind, user.telegram_id), stamp, ex=_ttl(window))
            return QuotaState(kind=kind, used=used, limit=limit, stamp=stamp)
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("quota.consume({}) unavailable: {}", kind, exc)
        return QuotaState(kind=kind, used=0, limit=limit, stamp=stamp, metered=False)


async def _booked_stamp(r, kind: str, telegram_id: int, fallback: str) -> str:
    """The window the last booking used, or ``fallback`` if Redis forgot it."""
    try:
        return str(await r.get(_booked_key(kind, telegram_id)) or fallback)
    except Exception as exc:  # noqa: BLE001 - a missing hint is not an error
        logger.debug("quota.release({}) window lookup failed: {}", kind, exc)
        return fallback


async def release(
    kind: str,
    user: User,
    *,
    amount: int = 1,
    now: datetime | None = None,
    stamp: str | None = None,
) -> None:
    """Give a unit back (e.g. the photo could not be analysed after all).

    The window is resolved in decreasing order of certainty: the ``stamp`` the
    booking returned, else the booking time in ``now``, else the window Redis
    remembers from the last :func:`consume`, else the current one. Without that
    ladder a refund issued just after midnight (or just after the first of the
    month) decrements the fresh counter and leaves the old one inflated.
    """
    try:
        async with _redis() as r:
            current = _stamp(_WINDOW[kind], now)
            window = stamp or (
                current
                if now is not None
                else await _booked_stamp(r, kind, user.telegram_id, current)
            )
            key = _key_for(kind, user.telegram_id, window)
            if int(await r.get(key) or 0) >= amount:
                await r.decrby(key, amount)
    except Exception as exc:  # noqa: BLE001
        logger.debug("quota.release({}) unavailable: {}", kind, exc)


async def snapshot(user: User) -> dict[str, QuotaState]:
    """Every metered kind at once — for /usage and the Mini App.

    The daily photo brake is included: for the levels with unlimited monthly
    valuations it is the only quota that can refuse one, so a usage page that
    omits it cannot explain the refusal it is there to explain.
    """
    kinds = (KIND_CARDS, KIND_PHOTO, KIND_PHOTO_DAY, KIND_QUICK, KIND_NEGO)
    states = {kind: await check(kind, user) for kind in kinds}
    # Only worth showing when the monthly quota cannot already explain a "no".
    if not states[KIND_PHOTO].unlimited:
        states.pop(KIND_PHOTO_DAY)
    return states


#: Text key describing what one unit of each kind is, per language.
_UNIT_KEY = {
    KIND_CARDS: "quota.unit.cards",
    KIND_PHOTO: "quota.unit.photo",
    KIND_QUICK: "quota.unit.quick",
    KIND_NEGO: "quota.unit.nego",
}


def upgrade_hint(kind: str, user: User, lang: str | None = None) -> str | None:
    """What the next level would give for this kind of action (HTML)."""
    from app.bot.texts import t

    nxt = ent.next_tier(user.subscription)
    if nxt is None or kind not in _UNIT_KEY:
        return None
    e = ent.for_tier(nxt)
    amount = {
        KIND_CARDS: e.daily_notifications,
        KIND_PHOTO: e.photo_evals_per_month,
        KIND_QUICK: e.quick_searches_per_day,
        KIND_NEGO: e.negotiations_per_month,
    }[kind]
    value = f"{ent.fmt_quota(amount, lang=lang)} {t(_UNIT_KEY[kind], lang)}"
    return t("quota.upgrade_hint", lang, level=e.label, value=value)
