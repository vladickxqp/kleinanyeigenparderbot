"""Admin-only commands (restricted to BOT_ADMIN_IDS).

/admin — dashboard: users, premium, revenue, system status.
/settier <telegram_id> <free|pro|unlimited> — change a user's tier manually.
/tiers — list all users with their tier and rule quota usage.
/grant <telegram_id> <tage> — grant premium for N days (admin gift).
/revoke <telegram_id> — end a user's premium immediately.
/broadcast <text> — message all active users (use responsibly).

Every admin action is logged.
"""

from __future__ import annotations

import asyncio
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import (
    Listing,
    PlanType,
    SearchRule,
    Subscription,
    SubscriptionStatus,
    User,
)
from app.database.models.enums import SubscriptionTier
from app.services import health
from app.services import premium as premium_svc

router = Router(name="admin")

#: Tiers that can be assigned via /settier (legacy values are not offered).
ASSIGNABLE_TIERS = {
    "free": SubscriptionTier.FREE,
    "pro": SubscriptionTier.PRO,
    "unlimited": SubscriptionTier.UNLIMITED,
}


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


# --- Dashboard --------------------------------------------------------------------
@router.message(Command("admin", "dashboard"))
async def cmd_admin(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message):
        return
    logger.info("ADMIN: dashboard requested by {}", message.from_user.id)

    total_users = await session.scalar(select(func.count(User.id))) or 0
    active_users = (
        await session.scalar(
            select(func.count(User.id)).where(User.is_active.is_(True))
        )
        or 0
    )
    paid_users = (
        await session.scalar(
            select(func.count(User.id)).where(
                User.subscription != SubscriptionTier.FREE
            )
        )
        or 0
    )
    active_subs = (
        await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.ACTIVE
            )
        )
        or 0
    )
    payments = (
        await session.scalar(
            select(func.coalesce(func.sum(Subscription.payments_count), 0))
        )
        or 0
    )
    revenue_eur = float(payments) * settings.premium_price_eur
    total_rules = await session.scalar(select(func.count(SearchRule.id))) or 0
    active_rules = (
        await session.scalar(
            select(func.count(SearchRule.id)).where(SearchRule.is_active.is_(True))
        )
        or 0
    )
    total_listings = await session.scalar(select(func.count(Listing.id))) or 0

    status = await health.get_status()
    worker = "🟢 läuft" if status.worker_alive else "🔴 KEIN Lebenszeichen"

    await message.answer(
        "👑 <b>Admin-Dashboard</b>\n\n"
        f"👥 Nutzer: <b>{total_users}</b> (aktiv: {active_users})\n"
        f"💎 Premium: <b>{paid_users}</b> · aktive Abos: {active_subs}\n"
        f"💰 Zahlungen: <b>{payments}</b> ≈ {revenue_eur:.2f} €\n\n"
        f"📋 Suchen: <b>{active_rules}</b>/{total_rules} aktiv\n"
        f"🛒 Angebote gesamt: <b>{total_listings}</b>\n"
        f"🔄 Suchläufe heute: <b>{status.runs_today}</b>\n"
        f"📨 Karten heute: <b>{status.cards_sent_today}</b>\n\n"
        f"⚙️ Worker: {worker}\n"
        "👥 Nutzerliste: /tiers · Status: /status"
    )


# --- Tier management ---------------------------------------------------------------
@router.message(Command("settier"))
async def cmd_settier(
    message: Message, session: AsyncSession, command: CommandObject
) -> None:
    if not _is_admin(message):
        return  # silently ignore for non-admins

    args = (command.args or "").split()
    if len(args) != 2 or args[1].lower() not in ASSIGNABLE_TIERS:
        await message.answer(
            "Nutzung: <code>/settier &lt;telegram_id&gt; "
            "&lt;free|pro|unlimited&gt;</code>\n"
            "Beispiel: <code>/settier 123456789 pro</code>"
        )
        return

    raw_id, tier_name = args
    try:
        target_id = int(raw_id)
    except ValueError:
        await message.answer("⚠️ Die Telegram-ID muss eine Zahl sein.")
        return

    result = await session.execute(select(User).where(User.telegram_id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        await message.answer(
            f"⚠️ Kein Nutzer mit ID <code>{target_id}</code> gefunden — "
            "die Person muss den Bot zuerst mit /start benutzt haben."
        )
        return

    target.subscription = ASSIGNABLE_TIERS[tier_name.lower()]
    await session.flush()
    logger.info(
        "ADMIN: {} set tier of {} to {}",
        message.from_user.id, target_id, target.subscription.value,
    )
    await message.answer(
        f"✅ <b>{escape(target.display_name)}</b> (ID {target.telegram_id}) "
        f"ist jetzt <b>{target.subscription.value}</b> "
        f"(max. {target.max_rules if target.max_rules < 1_000_000 else '∞'} Suchen)."
    )


@router.message(Command("tiers", "users"))
async def cmd_tiers(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message):
        return

    rules_count = (
        select(SearchRule.user_id, func.count(SearchRule.id).label("cnt"))
        .group_by(SearchRule.user_id)
        .subquery()
    )
    result = await session.execute(
        select(User, func.coalesce(rules_count.c.cnt, 0))
        .outerjoin(rules_count, rules_count.c.user_id == User.id)
        .order_by(User.created_at.asc())
        .limit(50)
    )
    rows = result.all()
    if not rows:
        await message.answer("Noch keine Nutzer.")
        return

    lines = ["👥 <b>Nutzer & Tarife</b>\n"]
    for user, cnt in rows:
        quota = "∞" if user.max_rules >= 1_000_000 else str(user.max_rules)
        badge = " 💎" if user.is_paid_tier else ""
        lines.append(
            f"• <b>{escape(user.display_name)}</b>{badge} "
            f"(<code>{user.telegram_id}</code>) — "
            f"{user.subscription.value}, Suchen: {cnt}/{quota}"
        )
    lines.append("\nÄndern: <code>/settier &lt;id&gt; &lt;free|pro|unlimited&gt;</code>")
    await message.answer("\n".join(lines))


# --- Premium grant / revoke ----------------------------------------------------------
@router.message(Command("grant"))
async def cmd_grant(
    message: Message, session: AsyncSession, command: CommandObject
) -> None:
    if not _is_admin(message):
        return

    args = (command.args or "").split()
    if not args:
        await message.answer(
            "Nutzung: <code>/grant &lt;telegram_id&gt; [tage]</code> (Standard: 31)"
        )
        return
    try:
        target_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else settings.premium_period_days
    except ValueError:
        await message.answer("⚠️ ID und Tage müssen Zahlen sein.")
        return

    result = await session.execute(select(User).where(User.telegram_id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        await message.answer(f"⚠️ Kein Nutzer mit ID <code>{target_id}</code>.")
        return

    sub = await premium_svc.activate_premium(
        session, target, days=days, provider="admin_grant", plan=PlanType.ADMIN_GRANT
    )
    logger.info(
        "ADMIN: {} granted premium to {} for {}d",
        message.from_user.id, target_id, days,
    )
    await message.answer(
        f"✅ <b>{escape(target.display_name)}</b> hat Premium bis "
        f"<b>{sub.subscription_end:%d.%m.%Y}</b>."
    )


@router.message(Command("revoke"))
async def cmd_revoke(
    message: Message, session: AsyncSession, command: CommandObject
) -> None:
    if not _is_admin(message):
        return

    args = (command.args or "").split()
    if not args:
        await message.answer("Nutzung: <code>/revoke &lt;telegram_id&gt;</code>")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await message.answer("⚠️ Die Telegram-ID muss eine Zahl sein.")
        return

    result = await session.execute(select(User).where(User.telegram_id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        await message.answer(f"⚠️ Kein Nutzer mit ID <code>{target_id}</code>.")
        return

    await premium_svc.deactivate_premium(session, target)
    logger.info("ADMIN: {} revoked premium of {}", message.from_user.id, target_id)
    await message.answer(
        f"✅ Premium von <b>{escape(target.display_name)}</b> beendet (jetzt Free)."
    )


# --- Broadcast ------------------------------------------------------------------------
@router.message(Command("broadcast"))
async def cmd_broadcast(
    message: Message, session: AsyncSession, command: CommandObject
) -> None:
    if not _is_admin(message):
        return

    text = (command.args or "").strip()
    if not text:
        await message.answer(
            "Nutzung: <code>/broadcast &lt;Nachricht&gt;</code>\n"
            "Wird an ALLE aktiven Nutzer gesendet."
        )
        return

    result = await session.execute(
        select(User.telegram_id).where(
            User.is_active.is_(True), User.is_blocked.is_(False)
        )
    )
    targets = list(result.scalars().all())
    logger.info(
        "ADMIN: {} broadcasting to {} user(s)", message.from_user.id, len(targets)
    )

    sent = 0
    for tg_id in targets:
        try:
            await message.bot.send_message(tg_id, f"📢 {escape(text)}")
            sent += 1
        except Exception:  # noqa: BLE001 - blocked users etc.
            pass
        await asyncio.sleep(0.05)  # stay well under Telegram's rate limits
    await message.answer(f"📢 Broadcast an <b>{sent}/{len(targets)}</b> Nutzer gesendet.")
