"""Broadcast engine: audiences, scheduling, rate-limited delivery, statistics.

The delivery loop is transport-agnostic — it receives an async ``send_fn``
that returns a :class:`SendResult` — so the worker plugs in Telegram while the
tests plug in a fake. Blocked recipients are deactivated on the spot, which
keeps every later broadcast (and deal delivery) from wasting calls on them.
"""

from __future__ import annotations

import asyncio
import enum
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Broadcast,
    BroadcastAudience,
    BroadcastStatus,
    SubscriptionTier,
    User,
)

#: Telegram allows ~30 msgs/s to different chats; we stay far below it.
DEFAULT_PACE_SECONDS = 0.05
#: Report progress to the admin every N recipients.
PROGRESS_EVERY = 25


class SendResult(enum.Enum):
    SENT = "sent"
    BLOCKED = "blocked"   # user blocked the bot / deleted account
    FAILED = "failed"     # anything else (network, flood, bad media)


SendFn = Callable[[int], Awaitable[SendResult]]
ProgressFn = Callable[[int, int], Awaitable[None]]


# --- Audience -------------------------------------------------------------------------
async def audience_telegram_ids(
    session: AsyncSession, audience: BroadcastAudience
) -> list[int]:
    """Active, non-blocked users of the segment."""
    stmt = select(User.telegram_id).where(
        User.is_active.is_(True), User.is_blocked.is_(False)
    )
    if audience is BroadcastAudience.FREE:
        stmt = stmt.where(User.subscription == SubscriptionTier.FREE)
    elif audience is BroadcastAudience.PREMIUM:
        stmt = stmt.where(User.subscription != SubscriptionTier.FREE)
    result = await session.execute(stmt.order_by(User.id.asc()))
    return list(result.scalars().all())


# --- Scheduling -------------------------------------------------------------------------
_RELATIVE = re.compile(r"^(\d+)\s*([mhd])$", re.IGNORECASE)
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE_CLOCK = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?\s+(\d{1,2}):(\d{2})$")


def parse_schedule(text: str, now: datetime | None = None) -> datetime | None:
    """Parse when to send. ``None`` means "right now".

    Accepted: ``jetzt``/``now`` · ``30m`` / ``2h`` / ``1d`` · ``18:30`` (today,
    or tomorrow if already past) · ``24.12. 18:00``. Times are local (the
    container runs in the configured TZ). Raises ``ValueError`` otherwise.
    """
    raw = text.strip().lower()
    now = now or datetime.now()
    if raw in ("", "jetzt", "now", "sofort"):
        return None
    if m := _RELATIVE.match(raw):
        amount, unit = int(m.group(1)), m.group(2)
        delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount),
                 "d": timedelta(days=amount)}[unit]
        return now + delta
    if m := _CLOCK.match(raw):
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError("Ungültige Uhrzeit")
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)
    if m := _DATE_CLOCK.match(raw):
        day, month, hour, minute = (int(g) for g in m.groups())
        candidate = now.replace(month=month, day=day, hour=hour, minute=minute,
                                second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate.replace(year=now.year + 1)
        return candidate
    raise ValueError("Format nicht erkannt (z. B. 2h, 18:30 oder 24.12. 18:00)")


# --- Lifecycle ----------------------------------------------------------------------------
async def create_broadcast(
    session: AsyncSession,
    *,
    created_by: int,
    audience: BroadcastAudience,
    preview: str,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
    text: str | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
    scheduled_at: datetime | None = None,
    status_chat_id: int | None = None,
    status_message_id: int | None = None,
) -> Broadcast:
    if source_message_id is None and not text:
        raise ValueError("Broadcast needs a source message or text")
    broadcast = Broadcast(
        created_by=created_by,
        audience=audience,
        preview=preview[:200],
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        text=text,
        button_text=button_text,
        button_url=button_url,
        scheduled_at=scheduled_at,
        status=BroadcastStatus.SCHEDULED,
        status_chat_id=status_chat_id,
        status_message_id=status_message_id,
    )
    session.add(broadcast)
    await session.flush()
    logger.info(
        "BROADCAST: {} created #{} ({}, {})",
        created_by, broadcast.id, audience.value,
        f"at {scheduled_at:%d.%m %H:%M}" if scheduled_at else "now",
    )
    return broadcast


async def claim_due(session: AsyncSession, now: datetime | None = None) -> list[int]:
    """Atomically move due broadcasts to SENDING; return their ids.

    Immediate broadcasts (``scheduled_at`` NULL) are due at once; scheduled
    ones once their time has come. Claiming before enqueuing prevents a
    second dispatcher tick from sending the same broadcast twice.
    """
    now = now or datetime.now(timezone.utc)
    result = await session.execute(
        select(Broadcast).where(Broadcast.status == BroadcastStatus.SCHEDULED)
    )
    due: list[int] = []
    for b in result.scalars().all():
        when = b.scheduled_at
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when is None or when <= now:
            b.status = BroadcastStatus.SENDING
            due.append(b.id)
    await session.flush()
    return due


async def cancel_scheduled(session: AsyncSession, broadcast_id: int) -> bool:
    b = await session.get(Broadcast, broadcast_id)
    if b is None or b.status is not BroadcastStatus.SCHEDULED:
        return False
    b.status = BroadcastStatus.CANCELED
    await session.flush()
    return True


async def run_broadcast(
    session: AsyncSession,
    broadcast: Broadcast,
    send_fn: SendFn,
    *,
    progress_fn: ProgressFn | None = None,
    pace_seconds: float = DEFAULT_PACE_SECONDS,
    progress_every: int = PROGRESS_EVERY,
) -> Broadcast:
    """Deliver to the audience with rate limiting, counting every outcome."""
    ids = await audience_telegram_ids(session, broadcast.audience)
    broadcast.total = len(ids)
    broadcast.status = BroadcastStatus.SENDING
    broadcast.started_at = datetime.now(timezone.utc)
    await session.flush()

    for index, tg_id in enumerate(ids, start=1):
        try:
            result = await send_fn(tg_id)
        except Exception as exc:  # noqa: BLE001 - one recipient never aborts the run
            logger.warning("BROADCAST #{}: send to {} raised {}", broadcast.id, tg_id, exc)
            result = SendResult.FAILED

        if result is SendResult.SENT:
            broadcast.sent += 1
        elif result is SendResult.BLOCKED:
            broadcast.blocked += 1
            user = (
                await session.execute(select(User).where(User.telegram_id == tg_id))
            ).scalar_one_or_none()
            if user is not None:
                user.is_active = False
        else:
            broadcast.failed += 1

        if progress_fn is not None and (index % progress_every == 0 or index == len(ids)):
            try:
                await progress_fn(index, len(ids))
            except Exception:  # noqa: BLE001 - progress is best effort
                pass
        if pace_seconds:
            await asyncio.sleep(pace_seconds)

    broadcast.status = BroadcastStatus.DONE
    broadcast.finished_at = datetime.now(timezone.utc)
    await session.flush()
    logger.info(
        "BROADCAST #{} done: {} sent, {} blocked, {} failed of {}",
        broadcast.id, broadcast.sent, broadcast.blocked, broadcast.failed, broadcast.total,
    )
    return broadcast


async def recent_broadcasts(session: AsyncSession, limit: int = 10) -> list[Broadcast]:
    result = await session.execute(
        select(Broadcast).order_by(Broadcast.created_at.desc(), Broadcast.id.desc()).limit(limit)
    )
    return list(result.scalars().all())


# --- Presentation (HTML, shared by bot and admin panel) -------------------------------
_STATUS_ICON = {
    BroadcastStatus.SCHEDULED: "⏰",
    BroadcastStatus.SENDING: "📤",
    BroadcastStatus.DONE: "✅",
    BroadcastStatus.FAILED: "❌",
    BroadcastStatus.CANCELED: "✖️",
}
_AUDIENCE_LABEL = {
    BroadcastAudience.ALL: "Alle",
    BroadcastAudience.FREE: "Free",
    BroadcastAudience.PREMIUM: "Premium",
}


def audience_label(audience: BroadcastAudience) -> str:
    return _AUDIENCE_LABEL[audience]


def summary_line(b: Broadcast) -> str:
    """One-line HTML summary for lists."""
    from html import escape

    icon = _STATUS_ICON[b.status]
    when = (
        f"geplant {b.scheduled_at:%d.%m. %H:%M}"
        if b.status is BroadcastStatus.SCHEDULED and b.scheduled_at
        else f"{b.created_at:%d.%m. %H:%M}"
    )
    stats = (
        f"{b.sent}/{b.total} ✅ · {b.blocked} 🚫 · {b.failed} ⚠️"
        if b.status in (BroadcastStatus.SENDING, BroadcastStatus.DONE)
        else audience_label(b.audience)
    )
    return f"{icon} <b>#{b.id}</b> {escape(b.preview[:40] or '(Medien)')} — {stats} · {when}"


def format_report(b: Broadcast) -> str:
    """Final delivery report shown to the admin."""
    return (
        f"✅ <b>Broadcast #{b.id} fertig</b>\n\n"
        f"👥 Zielgruppe: {audience_label(b.audience)} ({b.total})\n"
        f"📨 Zugestellt: <b>{b.sent}</b>\n"
        f"🚫 Blockiert (deaktiviert): {b.blocked}\n"
        f"⚠️ Fehler: {b.failed}"
    )
