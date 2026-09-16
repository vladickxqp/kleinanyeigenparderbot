"""Celery tasks: dispatch due searches, run one rule, deliver notifications.

Async work is bridged into Celery's sync world via :func:`_run_async`, which
wraps :func:`asyncio.run` and disposes the database engine at the end of every
task — pooled asyncpg connections are bound to the event loop they were created
on, and the next task runs in a fresh loop, so reusing them raises
``RuntimeError``. Per-rule scheduling is enforced with Redis keys
(``rule:next_run:<id>``) so we don't need an extra DB column or a beat entry
per rule.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from typing import Any, TypeVar

import redis
from loguru import logger

from app.bot.notifier import notify_user_about_listings
from app.config.settings import settings
from app.database.models import SubscriptionTier, User
from app.database.session import dispose_engine, session_scope
from app.services.repositories import SearchRuleRepository
from app.services.search_service import SearchService
from app.worker.celery_app import celery_app

_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)

T = TypeVar("T")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine in a fresh loop and ALWAYS dispose the DB engine in it.

    Without the dispose step, the second task executed by a worker child
    process crashes with "RuntimeError: ... attached to a different loop",
    because the engine's pooled connections belong to the previous task's
    (already closed) event loop.
    """

    async def wrapper() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(wrapper())


def _next_run_key(rule_id: int) -> str:
    return f"rule:next_run:{rule_id}"


#: Runs one owner may start per day, as (settings prefix, fallback). This is an
#: infrastructure brake that keeps the promise affordable when a few accounts
#: run hundreds of rules — it is deliberately never shown or sold, and sits far
#: above what normal use of a level reaches.
_RUN_BUDGET: dict[SubscriptionTier, str] = {
    SubscriptionTier.FREE: "free",
    SubscriptionTier.STARTER: "starter",
    SubscriptionTier.PRO: "pro",
    SubscriptionTier.UNLIMITED: "dealer",
}


def _runs_key(user_id: int) -> str:
    return f"budget:runs:{user_id}:{time.strftime('%Y%m%d')}"


def _daily_run_budget(owner: User) -> int:
    prefix = _RUN_BUDGET[owner.subscription.canonical]
    return int(getattr(settings, f"{prefix}_max_runs_per_day"))


def _take_run_budget(owner: User) -> bool:
    """Claim one of today's runs for ``owner``; False once the budget is spent.

    Fails OPEN: a Redis problem must never stop the searches people paid for.
    """
    budget = _daily_run_budget(owner)
    if budget < 0:  # the ladder's "unlimited" convention
        return True
    try:
        key = _runs_key(owner.id)
        if int(_redis.get(key) or 0) >= budget:
            return False
        if _redis.incr(key) == 1:
            _redis.expire(key, 2 * 86400)
        return True
    except Exception as exc:  # noqa: BLE001 - fail open
        logger.debug("Run budget check failed for user {}: {}", owner.id, exc)
        return True


# --- Dispatcher -------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.dispatch_due_searches")
def dispatch_due_searches() -> int:
    """Enqueue ``run_search_rule`` for every active rule whose interval elapsed."""
    return _run_async(_dispatch_due_searches())


#: Most rules started per tick. After the machine was offline for hours every
#: rule is overdue at once; without a cap the first tick would fire all of them
#: and hammer the marketplaces into a block.
MAX_DISPATCH_PER_TICK = 25


async def _dispatch_due_searches() -> int:
    import random

    from app.services import health

    now = time.time()
    dispatched = 0
    over_budget = 0
    # A suspected block widens every interval for a while: a ban would hit
    # exactly the paying users who were sold speed.
    backoff = await health.block_multiplier()
    async with session_scope() as session:
        rules = await SearchRuleRepository(session).list_active()
        # Oldest due first, so a capped tick never starves the same rules.
        due: list[tuple[float, object]] = []
        for rule in rules:
            raw = _redis.get(_next_run_key(rule.id))
            next_run = float(raw) if raw is not None else 0.0
            if next_run > now:
                continue
            due.append((next_run, rule))
        due.sort(key=lambda pair: pair[0])

        owners: dict[int, User] = {}
        for _, rule in due[:MAX_DISPATCH_PER_TICK]:
            owner = owners.get(rule.user_id)
            if owner is None:
                owner = await session.get(User, rule.user_id)
                if owner is not None:
                    owners[rule.user_id] = owner
            # The stored interval was reconciled against the tier (fast slots,
            # base interval) when it was set; here only the hard floor applies.
            floor = settings.scraper_hard_min_interval_seconds
            if owner is not None:
                floor = max(floor, owner.min_interval_seconds)
            interval = max(rule.interval_seconds, floor) * backoff
            # Jitter keeps many rules of the same interval from lining up.
            _redis.set(_next_run_key(rule.id), now + interval + random.uniform(0, 5))
            # Reschedule BEFORE the budget check: a skipped rule that stayed due
            # would sort first forever and starve everyone else out of the tick.
            if owner is not None and not _take_run_budget(owner):
                over_budget += 1
                continue
            # Each level has its own queue; "express" is served first.
            queue = owner.entitlements.queue_name if owner is not None else "celery"
            run_search_rule.apply_async(args=[rule.id], queue=queue)
            dispatched += 1

    await health.mark_dispatch()
    if dispatched or over_budget:
        logger.info(
            "Dispatched {}/{} due search rule(s){}",
            dispatched, len(due),
            f", {over_budget} over their daily run budget" if over_budget else "",
        )
    return dispatched


# --- Per-rule execution -----------------------------------------------------
@celery_app.task(
    name="app.worker.tasks.run_search_rule",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def run_search_rule(self, rule_id: int) -> dict:  # noqa: ANN001
    try:
        return _run_async(_run_search_rule(rule_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_search_rule({}) failed: {}", rule_id, exc)
        raise self.retry(exc=exc) from exc


async def _run_search_rule(rule_id: int) -> dict:
    from app.services.throttle import rule_lock

    notable_ids: list[int] = []
    telegram_id: int | None = None
    lang = "de"

    # A slow run must not be started again by the next dispatcher tick: two
    # concurrent runs read the same "already known" set and insert duplicates.
    async with rule_lock(rule_id) as acquired:
        if not acquired:
            logger.info("Rule {} is already running — skipping this tick", rule_id)
            return {"rule_id": rule_id, "skipped": "running"}

        async with session_scope() as session:
            repo = SearchRuleRepository(session)
            rule = await repo.get_unscoped(rule_id)
            if rule is None or not rule.is_active:
                return {"rule_id": rule_id, "skipped": True}

            service = SearchService(session)
            notable = await service.run_rule(rule)
            notable_ids = [row.id for row in notable]

            # Grab the owner's telegram id + language for notification.
            owner = await session.get(User, rule.user_id)
            if owner is not None:
                telegram_id = owner.telegram_id
                lang = owner.language_code

    from app.services import health

    await health.record_rule_run()

    if notable_ids and telegram_id is not None:
        deliver_notifications.delay(telegram_id, notable_ids, lang)

    return {"rule_id": rule_id, "new_notable": len(notable_ids)}


# --- Notification delivery --------------------------------------------------
@celery_app.task(name="app.worker.tasks.deliver_notifications")
def deliver_notifications(
    telegram_id: int, listing_ids: list[int], lang: str = "de"
) -> int:
    return _run_async(notify_user_about_listings(telegram_id, listing_ids, lang))


# --- Admin health alerts ------------------------------------------------------
@celery_app.task(name="app.worker.tasks.flush_health_alerts")
def flush_health_alerts() -> int:
    """Deliver queued health alerts to all configured bot admins."""
    return _run_async(_flush_health_alerts())


async def _flush_health_alerts() -> int:
    from app.services import health

    admin_ids = settings.admin_ids
    if not admin_ids or not settings.bot_token:
        return 0
    messages = await health.pop_alerts()
    if not messages:
        return 0

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    sent = 0
    try:
        for message in messages:
            for admin_id in admin_ids:
                try:
                    await bot.send_message(admin_id, message)
                    sent += 1
                except Exception as exc:  # noqa: BLE001 - one admin must not block others
                    logger.warning("Health alert to {} failed: {}", admin_id, exc)
    finally:
        await bot.session.close()
    return sent


# --- Daily heartbeat ------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.daily_heartbeat")
def daily_heartbeat() -> int:
    """Evening summary to the admins: the bot proves it is alive."""
    return _run_async(_daily_heartbeat())


async def _daily_heartbeat() -> int:
    from sqlalchemy import func, select

    from app.database.models import Listing
    from app.services import health

    admin_ids = settings.admin_ids
    if not admin_ids or not settings.bot_token:
        return 0

    status = await health.get_status()

    # Listings discovered in the last 24h (across all rules).
    async with session_scope() as session:
        since = time.time() - 86400
        new_today = await session.scalar(
            select(func.count(Listing.id)).where(
                Listing.created_at >= func.to_timestamp(since)
            )
        ) or 0

    worker_icon = "🟢" if status.worker_alive else "🔴"
    message = (
        "🫀 <b>Täglicher Statusbericht</b>\n\n"
        f"{worker_icon} Worker: {'läuft' if status.worker_alive else 'KEIN Lebenszeichen!'}\n"
        f"🔄 Suchläufe heute: <b>{status.runs_today}</b>\n"
        f"🆕 Neue Angebote (24h): <b>{new_today}</b>\n"
        f"📨 Karten gesendet heute: <b>{status.cards_sent_today}</b>\n\n"
        "ℹ️ Keine Karten trotz Suchläufen = es gab nichts wirklich Neues. "
        "Jederzeit prüfen: /status"
    )

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    sent = 0
    try:
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, message)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Heartbeat to {} failed: {}", admin_id, exc)
    finally:
        await bot.session.close()
    return sent


# --- Morning digest -----------------------------------------------------------
@celery_app.task(name="app.worker.tasks.flush_digests")
def flush_digests() -> int:
    """Deliver queued quiet-hour cards once each user's window has ended."""
    return _run_async(_flush_digests())


async def _flush_digests() -> int:
    from sqlalchemy import select

    from app.services import quiet

    delivered = 0
    for tg_id in await quiet.users_with_pending_digest():
        if await quiet.is_quiet_now(tg_id):
            continue  # still sleeping

        # Pop ONLY one batch per cycle: anything popped but not delivered
        # would be lost forever, so the remainder stays queued and follows
        # with the next beat run (10 minutes later).
        total = await quiet.digest_size(tg_id)
        ids = await quiet.pop_digest(tg_id, limit=quiet.DIGEST_MAX_CARDS)
        if not ids:
            continue
        remaining = max(0, total - len(ids))

        async with session_scope() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == tg_id)
            )
            user = result.scalar_one_or_none()
        lang = user.language_code if user else "de"

        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            note = (
                f" — die besten {len(ids)} jetzt, {remaining} weitere folgen gleich"
                if remaining
                else ""
            )
            await bot.send_message(
                tg_id,
                f"☀️ Aus deiner Ruhezeit: <b>{total}</b> neue Angebot(e){note}.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Digest summary to {} failed: {}", tg_id, exc)
        finally:
            await bot.session.close()

        delivered += await notify_user_about_listings(tg_id, ids, lang)
    return delivered


# --- Subscription expiry --------------------------------------------------------
@celery_app.task(name="app.worker.tasks.check_expired_subscriptions")
def check_expired_subscriptions() -> int:
    """Downgrade users whose premium period ended (no renewal charge arrived)."""
    return _run_async(_check_expired_subscriptions())


async def _check_expired_subscriptions() -> int:
    from app.services.premium import expire_overdue_subscriptions

    async with session_scope() as session:
        downgraded = await expire_overdue_subscriptions(session)

    if not downgraded or not settings.bot_token:
        return len(downgraded)

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        for tg_id in downgraded:
            try:
                await bot.send_message(
                    tg_id,
                    "💎 Dein <b>Premium</b> ist abgelaufen — du bist jetzt "
                    "wieder im Free-Tarif.\n"
                    "Jederzeit zurückholen: /premium",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Expiry notice to {} failed: {}", tg_id, exc)
    finally:
        await bot.session.close()
    return len(downgraded)


# --- Weekly user recap ------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.send_weekly_recaps")
def send_weekly_recaps() -> int:
    """Tell every active user what the bot found for them this week."""
    return _run_async(_send_weekly_recaps())


async def _send_weekly_recaps() -> int:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from sqlalchemy import select

    from app.services import recap as recap_svc
    from app.services.referrals import build_referral_link

    if not settings.bot_token:
        return 0

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    sent = 0
    try:
        me = await bot.get_me()
        async with session_scope() as session:
            users = (
                await session.execute(
                    select(User).where(
                        User.is_active.is_(True), User.is_blocked.is_(False)
                    )
                )
            ).scalars().all()

            for user in users:
                try:
                    data = await recap_svc.build_recap(session, user)
                    if not data.worth_sending:
                        continue
                    link = build_referral_link(me.username, user.telegram_id)
                    await bot.send_message(
                        user.telegram_id,
                        recap_svc.format_recap(data, referral_link=link),
                        disable_web_page_preview=True,
                    )
                    sent += 1
                except Exception as exc:  # noqa: BLE001 - one user never stops the rest
                    logger.debug("Recap for {} failed: {}", user.telegram_id, exc)
                await asyncio.sleep(0.05)
    finally:
        await bot.session.close()

    logger.info("Weekly recap sent to {} user(s)", sent)
    return sent


# --- Win-back after expiry ----------------------------------------------------------
@celery_app.task(name="app.worker.tasks.send_winbacks")
def send_winbacks() -> int:
    """Nudge users a few days after their premium lapsed."""
    return _run_async(_send_winbacks())


#: Days after expiry when the win-back message goes out.
WINBACK_AFTER_DAYS = 5


async def _send_winbacks() -> int:
    from datetime import datetime, timedelta, timezone

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from sqlalchemy import select

    from app.database.models import Subscription, SubscriptionStatus

    if not settings.bot_token:
        return 0

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINBACK_AFTER_DAYS + 1)
    window_end = now - timedelta(days=WINBACK_AFTER_DAYS)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    sent = 0
    try:
        async with session_scope() as session:
            subs = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.status == SubscriptionStatus.EXPIRED,
                        Subscription.subscription_end >= window_start,
                        Subscription.subscription_end < window_end,
                    )
                )
            ).scalars().all()

            for sub in subs:
                user = await session.get(User, sub.user_id)
                if user is None or user.is_paid_tier or not user.is_active:
                    continue
                try:
                    await bot.send_message(
                        user.telegram_id,
                        "👋 Alles klar bei dir?\n\n"
                        "Seit ein paar Tagen läufst du wieder im Free-Tarif: "
                        f"maximal {user.max_rules} Suchen und Prüfung alle "
                        f"{user.min_interval_seconds // 60} Minuten.\n\n"
                        "Die besten Angebote sind meistens in den ersten "
                        "Minuten weg. Zurück zu Premium: /premium 💎",
                    )
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Win-back to {} failed: {}", user.telegram_id, exc)
                await asyncio.sleep(0.05)
    finally:
        await bot.session.close()

    if sent:
        logger.info("Win-back sent to {} lapsed user(s)", sent)
    return sent


# --- Watchdog ------------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.watchdog")
def watchdog() -> dict:
    """Notice a stalled pipeline in minutes instead of hours.

    Everything else in this system reports from the same machine that can fail,
    so silence looks exactly like "nothing to report". This task therefore does
    two things: it alerts the admins about problems it CAN see from inside, and
    it pings an external dead-man's switch. When the laptop, Docker or Postgres
    dies, that ping stops and the external service raises the alarm.
    """
    return _run_async(_watchdog())


async def _watchdog() -> dict:
    import shutil

    from app.services import health

    findings: list[str] = []
    status = await health.get_status()

    max_age = getattr(settings, "watchdog_max_dispatch_age", 600)
    if status.last_dispatch_age is not None and status.last_dispatch_age > max_age:
        findings.append(
            f"⚠️ Keine Suche seit {int(status.last_dispatch_age / 60)} Minuten — "
            "Worker oder Beat steht."
        )

    depth = await health.queue_depth()
    max_depth = getattr(settings, "watchdog_max_queue_depth", 100)
    if depth is not None and depth > max_depth:
        findings.append(
            f"⚠️ Warteschlange staut sich: {depth} Aufgaben offen — "
            "Worker kommt nicht hinterher."
        )

    try:
        usage = shutil.disk_usage("/")
        free_percent = usage.free / usage.total * 100
        min_free = getattr(settings, "watchdog_min_disk_free_percent", 10)
        if free_percent < min_free:
            findings.append(
                f"⚠️ Nur noch {free_percent:.1f}% Speicherplatz frei — "
                "Postgres stirbt bei voller Platte."
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("watchdog disk check failed: {}", exc)

    for index, message in enumerate(findings):
        await health.report(f"watchdog:{index}:{message[:40]}", message, dedup_ttl=3600)

    # Dead-man's switch: silence is what the external monitor reacts to.
    ping_url = getattr(settings, "healthcheck_ping_url", "")
    pinged = False
    if ping_url and not findings:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(ping_url)
            pinged = True
        except Exception as exc:  # noqa: BLE001 - a failed ping is itself the signal
            logger.warning("Healthcheck ping failed: {}", exc)

    return {"findings": len(findings), "queue": depth, "pinged": pinged}


# --- Rescue sweep ---------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.flush_unnotified")
def flush_unnotified() -> int:
    """Re-deliver listings that were stored but never sent.

    New rows are committed first and the delivery task is enqueued afterwards.
    If the worker dies in between, those listings would count as "already
    known" on the next run and could never reach the user. This sweep picks
    them up again.
    """
    return _run_async(_flush_unnotified())


#: Only rescue rows old enough that their normal delivery must have happened.
UNNOTIFIED_MIN_AGE_SECONDS = 600
UNNOTIFIED_MAX_PER_USER = 10


async def _flush_unnotified() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.database.models import Listing, SearchRule

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=UNNOTIFIED_MIN_AGE_SECONDS)
    rescued = 0
    async with session_scope() as session:
        result = await session.execute(
            select(Listing, SearchRule.user_id)
            .join(SearchRule, SearchRule.id == Listing.rule_id)
            .where(
                Listing.notified.is_(False),
                Listing.is_ignored.is_(False),
                Listing.created_at < cutoff,
                Listing.deal_score >= SearchRule.min_deal_score,
                SearchRule.is_active.is_(True),
            )
            .order_by(Listing.deal_score.desc())
            .limit(200)
        )
        by_user: dict[int, list[int]] = {}
        for listing, user_id in result.all():
            by_user.setdefault(user_id, []).append(listing.id)

        for user_id, listing_ids in by_user.items():
            owner = await session.get(User, user_id)
            if owner is None:
                continue
            batch = listing_ids[:UNNOTIFIED_MAX_PER_USER]
            deliver_notifications.delay(owner.telegram_id, batch, owner.language_code)
            rescued += len(batch)

    if rescued:
        logger.info("Rescued {} undelivered listing(s)", rescued)
    return rescued


# --- Data retention ---------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.purge_old_data")
def purge_old_data() -> dict:
    """Delete finds, price points and delivery records past their owner's window."""
    return _run_async(_purge_old_data())


async def _purge_old_data() -> dict:
    from app.services import retention

    async with session_scope() as session:
        stats = await retention.sweep(session)

    # Unbounded growth once filled this project's production disk, and from the
    # outside a sweep that silently stopped working looks exactly like a sweep
    # with nothing to do — so the numbers go into the health stats every night.
    await retention.record_sweep(stats)
    return {
        "listings": stats.listings,
        "price_points": stats.price_points,
        "notifications": stats.notifications,
        "capped": stats.capped,
    }


# --- Broadcasts -------------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.dispatch_broadcasts")
def dispatch_broadcasts() -> int:
    """Claim immediate and due scheduled broadcasts and enqueue their delivery."""
    return _run_async(_dispatch_broadcasts())


async def _dispatch_broadcasts() -> int:
    from app.services import broadcasts as bc_svc

    async with session_scope() as session:
        due = await bc_svc.claim_due(session)
    for broadcast_id in due:
        send_broadcast.delay(broadcast_id)
    return len(due)


@celery_app.task(name="app.worker.tasks.send_broadcast")
def send_broadcast(broadcast_id: int) -> dict:
    """Deliver one broadcast (rate-limited) with live progress for the admin."""
    return _run_async(_send_broadcast(broadcast_id))


async def _send_broadcast(broadcast_id: int) -> dict:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from app.database.models import Broadcast, BroadcastStatus
    from app.services import broadcasts as bc_svc
    from app.services.broadcasts import SendResult

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        async with session_scope() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None or broadcast.status not in (
                BroadcastStatus.SCHEDULED, BroadcastStatus.SENDING
            ):
                return {"id": broadcast_id, "skipped": True}

            markup = None
            if broadcast.button_text and broadcast.button_url:
                markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=broadcast.button_text, url=broadcast.button_url)
                ]])

            async def deliver(tg_id: int) -> SendResult:
                for attempt in range(2):
                    try:
                        if broadcast.source_message_id:
                            await bot.copy_message(
                                chat_id=tg_id,
                                from_chat_id=broadcast.source_chat_id,
                                message_id=broadcast.source_message_id,
                                reply_markup=markup,
                            )
                        else:
                            await bot.send_message(tg_id, broadcast.text or "", reply_markup=markup)
                        return SendResult.SENT
                    except TelegramRetryAfter as exc:
                        # Flood control: wait exactly as long as Telegram asks.
                        await asyncio.sleep(exc.retry_after + 1)
                        if attempt == 1:
                            return SendResult.FAILED
                    except TelegramForbiddenError:
                        return SendResult.BLOCKED
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Broadcast #{} to {} failed: {}", broadcast_id, tg_id, exc)
                        return SendResult.FAILED
                return SendResult.FAILED

            async def progress(done: int, total: int) -> None:
                if broadcast.status_chat_id and broadcast.status_message_id:
                    await bot.edit_message_text(
                        f"📢 Sende Broadcast #{broadcast.id}… <b>{done}/{total}</b>",
                        chat_id=broadcast.status_chat_id,
                        message_id=broadcast.status_message_id,
                    )

            await bc_svc.run_broadcast(session, broadcast, deliver, progress_fn=progress)

            if broadcast.status_chat_id and broadcast.status_message_id:
                try:
                    await bot.edit_message_text(
                        bc_svc.format_report(broadcast),
                        chat_id=broadcast.status_chat_id,
                        message_id=broadcast.status_message_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Broadcast report edit failed: {}", exc)
            return {
                "id": broadcast.id, "sent": broadcast.sent,
                "blocked": broadcast.blocked, "failed": broadcast.failed,
            }
    finally:
        await bot.session.close()
