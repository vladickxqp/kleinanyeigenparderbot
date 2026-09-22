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
#: After this many consecutive failures a site is not "having a bad minute",
#: it is down: every further run would only spend request budget on a page
#: that never answers. The site leaves the rotation and is probed instead.
DOWN_THRESHOLD = 12
#: How often a site that is down gets one real request to see whether it is
#: back. Every rule run would be the old behaviour; never would be a site
#: that stays dead after the marketplace fixed whatever it was.
PROBE_INTERVAL_SECONDS = 30 * 60
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
    """Track consecutive parser failures; escalate in two steps.

    At :data:`FAIL_THRESHOLD` the site is backed off: its intervals widen for a
    while, because a ban would hit exactly the paying users who were sold
    speed. At :data:`DOWN_THRESHOLD` it is taken out of the rotation entirely
    and probed on a slow cadence — a page that has refused twelve times in a
    row is not going to answer the thirteenth rule run either, and every
    request sent there was budget the working sites could have used.

    Both are per site. A marketplace that blocks the bot must never slow the
    marketplaces that do not: that used to be the case, and it meant one dead
    parser could stretch every paying user's interval on every site at once.
    """
    try:
        async with _redis() as r:
            fail_key = f"health:fail:{site}"
            if ok:
                await r.delete(fail_key)
                await r.delete(f"health:sent:parser:{site}")
                was_down = await r.delete(f"health:down:{site}")
                await r.delete(f"health:backoff:{site}")
                if was_down:
                    await r.delete(f"health:sent:down:{site}")
                    await report(
                        f"recovered:{site}",
                        f"✅ Parser <b>{site}</b> antwortet wieder — die Seite "
                        "ist zurück in der Rotation.",
                        dedup_ttl=3600,
                    )
                return
            count = await r.incr(fail_key)
            # No expiry refresh here: a site that fails every few minutes for
            # a day would otherwise carry a counter that never resets, and a
            # counter that never resets tells nobody anything.
            await r.expire(fail_key, 6 * 3600)
        if count == FAIL_THRESHOLD:
            await start_block_backoff(site)
            await report(
                f"parser:{site}",
                f"⚠️ Parser <b>{site}</b> ist {FAIL_THRESHOLD}× in Folge "
                "fehlgeschlagen.\nMögliche Ursachen: Seite blockiert den Bot, "
                "Layout geändert, Netzwerkproblem. Suchen auf <b>{site}</b> "
                f"laufen vorübergehend ×{settings.block_backoff_multiplier:g} "
                "langsamer; andere Seiten sind nicht betroffen. "
                "Details: <code>docker compose logs worker</code>",
            )
        elif count >= DOWN_THRESHOLD:
            await mark_site_down(site)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.record_parser_result failed: {}", exc)


async def start_block_backoff(site: str) -> None:
    """Widen this site's intervals for a while after a suspected block."""
    if not settings.block_backoff_enabled:
        return
    try:
        async with _redis() as r:
            await r.set(f"health:backoff:{site}", "1", ex=settings.block_backoff_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.start_block_backoff failed: {}", exc)


async def backed_off_sites() -> set[str]:
    """Sites currently under block backoff (empty on any Redis trouble)."""
    if not settings.block_backoff_enabled:
        return set()
    try:
        async with _redis() as r:
            keys = await r.keys("health:backoff:*")
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.backed_off_sites failed: {}", exc)
        return set()
    return {str(key).rsplit(":", 1)[-1] for key in keys}


def multiplier_for(sites, backed_off: set[str]) -> float:  # noqa: ANN001
    """Interval multiplier for a rule that searches ``sites``.

    Only a rule that actually touches a backed-off site slows down; the
    old fleet-wide multiplier let one blocked marketplace stretch every
    interval everywhere.
    """
    if not backed_off:
        return 1.0
    touched = {getattr(site, "value", site) for site in sites}
    return settings.block_backoff_multiplier if touched & backed_off else 1.0


async def block_multiplier(sites=None) -> float:  # noqa: ANN001
    """Interval multiplier the dispatcher applies (1.0 = normal operation).

    With ``sites`` the answer is specific to those marketplaces; without, it
    is the old fleet-wide answer, kept for callers that have no rule in hand.
    """
    backed_off = await backed_off_sites()
    if sites is None:
        return settings.block_backoff_multiplier if backed_off else 1.0
    return multiplier_for(sites, backed_off)


# --- Sites that are down ---------------------------------------------------------
async def mark_site_down(site: str) -> None:
    """Take a site out of the rotation; the admins hear about it once a day."""
    try:
        async with _redis() as r:
            # A generous expiry as a safety net only: recovery is detected by
            # the probe, not by waiting this out.
            await r.set(f"health:down:{site}", str(int(_time.time())), ex=7 * 86400)
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.mark_site_down failed: {}", exc)
        return
    await report(
        f"down:{site}",
        f"🔴 Parser <b>{site}</b> ist seit {DOWN_THRESHOLD} Läufen tot und wurde "
        "aus der Rotation genommen. Alle "
        f"{PROBE_INTERVAL_SECONDS // 60} min geht eine Testanfrage raus; "
        "antwortet die Seite wieder, kommt sie automatisch zurück.\n"
        "Bis dahin kostet sie kein Anfrage-Budget mehr.",
        dedup_ttl=24 * 3600,
    )


async def down_sites() -> set[str]:
    """Sites taken out of the rotation (empty on any Redis trouble)."""
    try:
        async with _redis() as r:
            keys = await r.keys("health:down:*")
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.down_sites failed: {}", exc)
        return set()
    return {str(key).rsplit(":", 1)[-1] for key in keys}


async def should_probe(site: str) -> bool:
    """Whether this run may send one request to a site that is down.

    True at most once per :data:`PROBE_INTERVAL_SECONDS` across the whole
    fleet — the probe is what brings a recovered site back, so it must
    happen; every run doing it would be the old behaviour.
    """
    try:
        async with _redis() as r:
            return bool(
                await r.set(f"health:probe:{site}", "1", nx=True, ex=PROBE_INTERVAL_SECONDS)
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("health.should_probe failed: {}", exc)
        # Without Redis nobody can coordinate the probe; failing open here
        # means the site is simply searched, as before.
        return True


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
