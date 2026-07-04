"""Celery tasks: dispatch due searches, run one rule, deliver notifications.

Async work is bridged into Celery's sync world with :func:`asyncio.run`. Per-rule
scheduling is enforced with Redis keys (``rule:next_run:<id>``) so we don't need an
extra DB column or a beat entry per rule.
"""

from __future__ import annotations

import asyncio
import time

import redis
from loguru import logger

from app.bot.notifier import notify_user_about_listings
from app.config.settings import settings
from app.database.models import User
from app.database.session import session_scope
from app.services.repositories import SearchRuleRepository
from app.services.search_service import SearchService
from app.worker.celery_app import celery_app

_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _next_run_key(rule_id: int) -> str:
    return f"rule:next_run:{rule_id}"


# --- Dispatcher -------------------------------------------------------------
@celery_app.task(name="app.worker.tasks.dispatch_due_searches")
def dispatch_due_searches() -> int:
    """Enqueue ``run_search_rule`` for every active rule whose interval elapsed."""
    return asyncio.run(_dispatch_due_searches())


async def _dispatch_due_searches() -> int:
    now = time.time()
    dispatched = 0
    async with session_scope() as session:
        rules = await SearchRuleRepository(session).list_active()
        for rule in rules:
            key = _next_run_key(rule.id)
            next_run = _redis.get(key)
            if next_run is not None and float(next_run) > now:
                continue
            _redis.set(key, now + rule.interval_seconds)
            run_search_rule.delay(rule.id)
            dispatched += 1
    if dispatched:
        logger.info("Dispatched {} due search rule(s)", dispatched)
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
        return asyncio.run(_run_search_rule(rule_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_search_rule({}) failed: {}", rule_id, exc)
        raise self.retry(exc=exc) from exc


async def _run_search_rule(rule_id: int) -> dict:
    notable_ids: list[int] = []
    telegram_id: int | None = None
    lang = "de"

    async with session_scope() as session:
        repo = SearchRuleRepository(session)
        rule = await repo.get(rule_id)
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

    if notable_ids and telegram_id is not None:
        deliver_notifications.delay(telegram_id, notable_ids, lang)

    return {"rule_id": rule_id, "new_notable": len(notable_ids)}


# --- Notification delivery --------------------------------------------------
@celery_app.task(name="app.worker.tasks.deliver_notifications")
def deliver_notifications(
    telegram_id: int, listing_ids: list[int], lang: str = "de"
) -> int:
    return asyncio.run(notify_user_about_listings(telegram_id, listing_ids, lang))


# --- Admin health alerts ------------------------------------------------------
@celery_app.task(name="app.worker.tasks.flush_health_alerts")
def flush_health_alerts() -> int:
    """Deliver queued health alerts to all configured bot admins."""
    return asyncio.run(_flush_health_alerts())


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
