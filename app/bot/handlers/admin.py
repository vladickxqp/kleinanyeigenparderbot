"""Admin area (role-based, never hardcoded-ID checks — see services/roles.py).

Text commands (power users) AND an inline panel (/admin) exist side by side:

/admin — dashboard with inline menu (users, payments, coupons, help)
/promote <telegram_id> <super_admin|admin|moderator|user> — OWNER only
/settier <telegram_id> <free|pro|unlimited> — ADMIN+
/tiers, /users — user list — MODERATOR+
/grant <telegram_id> [tage], /revoke <telegram_id> — ADMIN+
/newcoupon CODE percent=20|stars=50|days=7 [uses=N] [valid=TAGE] — ADMIN+
/coupons, /delcoupon CODE — ADMIN+
/broadcast, /broadcasts — see handlers/broadcast.py — ADMIN+

Every admin action is logged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import (
    Coupon,
    Listing,
    Payment,
    PlanType,
    Referral,
    SearchRule,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
)
from app.database.models.enums import SubscriptionTier
from app.services import coupons as coupon_svc
from app.services import entitlements as ent
from app.services import health
from app.services import premium as premium_svc
from app.services.roles import ASSIGNABLE_ROLES, effective_role, has_role, role_badge

router = Router(name="admin")

#: How far back the dashboard looks at the listings table. Without a bound the
#: counts turn into a full-table scan on every refresh, and the panel's refresh
#: button invites exactly that.
DASHBOARD_WINDOW_DAYS = 30

#: Tiers that can be assigned via /settier (legacy values are not offered).
ASSIGNABLE_TIERS = {
    "free": SubscriptionTier.FREE,
    "starter": SubscriptionTier.STARTER,
    "pro": SubscriptionTier.PRO,
    "profi": SubscriptionTier.PRO,
    "dealer": SubscriptionTier.UNLIMITED,
    "haendler": SubscriptionTier.UNLIMITED,
    "unlimited": SubscriptionTier.UNLIMITED,
}


def _panel_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Aktualisieren", callback_data="adminp:dash")
    kb.button(text="👥 Nutzer", callback_data="adminp:users")
    kb.button(text="💳 Zahlungen", callback_data="adminp:payments")
    kb.button(text="🎁 Coupons", callback_data="adminp:coupons")
    kb.button(text="🎫 Referrals", callback_data="adminp:referrals")
    kb.button(text="📢 Broadcasts", callback_data="adminp:broadcasts")
    kb.button(text="❓ Befehle", callback_data="adminp:help")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


async def _broadcasts_text(session: AsyncSession) -> str:
    from app.services import broadcasts as bc_svc

    items = await bc_svc.recent_broadcasts(session)
    if not items:
        return "📢 Noch keine Broadcasts. Starten: /broadcast"
    lines = ["📢 <b>Broadcasts</b>\n"] + [bc_svc.summary_line(b) for b in items]
    lines.append("\nNeu: /broadcast · Verwalten: /broadcasts")
    return "\n".join(lines)


# --- Panel text builders -------------------------------------------------------
async def _tier_pressure(session: AsyncSession) -> tuple[str, int, int, int]:
    """How the users spread over the four levels and how hard the card quota bites.

    Delivered cards are counted from the listings themselves rather than from
    the Redis meters: one query answers it for every user at once, and the
    ledger survives a metering outage.

    Users the metering exempts (``app.services.quota``: everyone in
    ``settings.admin_ids``) are left out of the pressure counts — they are never
    capped, so measuring them against a cap invented pressure that does not
    exist.
    """
    levels = ent.all_tiers()
    spread = {e.tier: 0 for e in levels}
    cap = {e.tier: e.daily_notifications for e in levels}
    rows = await session.execute(
        select(User.subscription, func.count(User.id)).group_by(User.subscription)
    )
    for tier, count in rows:
        spread[tier.canonical] += count
    labels = " · ".join(f"{e.label} <b>{spread[e.tier]}</b>" for e in levels)

    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    exempt = set(settings.admin_ids)
    delivered = await session.execute(
        select(User.telegram_id, User.subscription, func.count(Listing.id))
        .join(SearchRule, SearchRule.user_id == User.id)
        .join(Listing, Listing.rule_id == SearchRule.id)
        # Bounded by the delivery timestamp: only today's cards can press
        # against today's quota, so the join never walks the whole table.
        .where(Listing.notified_at >= midnight)
        .group_by(User.id, User.telegram_id, User.subscription)
    )
    near = at_limit = 0
    for telegram_id, tier, sent in delivered:
        if telegram_id in exempt:
            continue
        limit = cap[tier.canonical]
        if ent.is_unlimited(limit):
            continue
        if sent >= limit:
            at_limit += 1
        elif sent * 2 > limit:
            # Past halfway is the warning band: a share that needs no tuning knob.
            near += 1
    withheld = (
        await session.scalar(
            select(func.count(Listing.id)).where(
                Listing.withheld.is_(True), Listing.created_at >= midnight
            )
        )
        or 0
    )
    return labels, near, at_limit, withheld


async def _dashboard_text(session: AsyncSession) -> str:
    total_users = await session.scalar(select(func.count(User.id))) or 0
    active_users = (
        await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True)))
        or 0
    )
    paid_users = (
        await session.scalar(
            select(func.count(User.id)).where(User.subscription != SubscriptionTier.FREE)
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
    payments_count = (
        await session.scalar(
            select(func.count(Payment.id)).where(Payment.status == "paid")
        )
        or 0
    )
    revenue_eur = (
        await session.scalar(
            select(func.coalesce(func.sum(Payment.amount_eur), 0.0)).where(
                Payment.status == "paid", Payment.provider == "telegram_stars"
            )
        )
        or 0.0
    )
    total_rules = await session.scalar(select(func.count(SearchRule.id))) or 0
    active_rules = (
        await session.scalar(
            select(func.count(SearchRule.id)).where(SearchRule.is_active.is_(True))
        )
        or 0
    )
    # Bounded on purpose: an all-time count over `listings` is the one query
    # here that grows without limit, and the panel has a refresh button.
    listings_since = datetime.now(timezone.utc) - timedelta(days=DASHBOARD_WINDOW_DAYS)
    recent_listings = (
        await session.scalar(
            select(func.count(Listing.id)).where(Listing.created_at >= listings_since)
        )
        or 0
    )

    tiers, near_quota, at_quota, withheld_today = await _tier_pressure(session)

    status = await health.get_status()
    worker = "🟢 läuft" if status.worker_alive else "🔴 KEIN Lebenszeichen"
    queue = await health.queue_depth()

    from app.services.analytics import business_metrics, format_metrics

    metrics = await business_metrics(session)

    return (
        "👑 <b>Admin-Dashboard</b>\n\n"
        f"👥 Nutzer: <b>{total_users}</b> (aktiv: {active_users})\n"
        f"💎 Premium: <b>{paid_users}</b> · aktive Abos: {active_subs}\n"
        f"🏷 Stufen: {tiers}\n"
        f"💰 Gesamt: <b>{payments_count}</b> Zahlungen ≈ {revenue_eur:.2f} €\n\n"
        f"📨 Karten-Limit heute: <b>{at_quota}</b> am Limit · "
        f"{near_quota} über der Hälfte"
        + (f" · {withheld_today} zurückgehalten" if withheld_today else "")
        + "\n\n"
        f"{format_metrics(metrics)}\n\n"
        f"📋 Suchen: <b>{active_rules}</b>/{total_rules} aktiv\n"
        f"🛒 Angebote ({DASHBOARD_WINDOW_DAYS} Tage): <b>{recent_listings}</b>\n"
        f"🔄 Suchläufe heute: <b>{status.runs_today}</b>\n"
        f"📨 Karten heute: <b>{status.cards_sent_today}</b>\n\n"
        f"⚙️ Worker: {worker}"
        + (f" · Warteschlange: {queue}" if queue is not None else "")
    )


async def _users_text(session: AsyncSession) -> str:
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
        return "Noch keine Nutzer."
    lines = ["👥 <b>Nutzer & Tarife</b>\n"]
    for user, cnt in rows:
        quota = str(user.max_rules)
        badge = " 💎" if user.is_paid_tier else ""
        rbadge = role_badge(user)
        lines.append(
            f"• {rbadge}<b>{escape(user.display_name)}</b>{badge} "
            f"(<code>{user.telegram_id}</code>) — "
            f"{user.subscription.value}, Suchen: {cnt}/{quota}"
        )
    lines.append(
        "\nÄndern: <code>/settier &lt;id&gt; &lt;free|pro|unlimited&gt;</code> · "
        "Rolle: <code>/promote &lt;id&gt; &lt;rolle&gt;</code>"
    )
    return "\n".join(lines)


async def _payments_text(session: AsyncSession) -> str:
    result = await session.execute(
        select(Payment).order_by(Payment.created_at.desc()).limit(15)
    )
    payments = result.scalars().all()
    if not payments:
        return "💳 Noch keine Zahlungen."
    lines = ["💳 <b>Letzte Zahlungen</b>\n"]
    for p in payments:
        renewal = " 🔄" if p.is_renewal else ""
        coupon = f" 🎟{p.coupon_code}" if p.coupon_code else ""
        lines.append(
            f"• {p.created_at:%d.%m %H:%M} — <code>{p.telegram_id}</code>: "
            f"{p.amount_stars} ⭐ ({p.provider}, {p.status}){renewal}{coupon}"
        )
    return "\n".join(lines)


async def _coupons_text(session: AsyncSession) -> str:
    result = await session.execute(
        select(Coupon).order_by(Coupon.created_at.desc()).limit(25)
    )
    coupons = result.scalars().all()
    if not coupons:
        return (
            "🎁 Noch keine Coupons.\n\n"
            "Anlegen: <code>/newcoupon SOMMER25 percent=25 uses=100 valid=30</code>\n"
            "Vorteile: <code>percent=20</code> ODER <code>stars=50</code> "
            "ODER <code>days=7</code>"
        )
    lines = ["🎁 <b>Coupons</b>\n"]
    for c in coupons:
        state = "🟢" if c.is_active else "⚪️"
        if c.discount_percent:
            benefit = f"-{c.discount_percent}%"
        elif c.discount_fixed_stars:
            benefit = f"-{c.discount_fixed_stars}⭐"
        else:
            benefit = f"{c.free_days} Tage gratis"
        until = f" bis {c.valid_until:%d.%m.%y}" if c.valid_until else ""
        lines.append(
            f"{state} <code>{c.code}</code> — {benefit}, "
            f"{c.used_count}/{c.max_uses or '∞'} genutzt{until}"
        )
    lines.append(
        "\nNeu: <code>/newcoupon CODE percent=20 [uses=N] [valid=TAGE]</code> · "
        "Aus: <code>/delcoupon CODE</code>"
    )
    return "\n".join(lines)


async def _referrals_text(session: AsyncSession) -> str:
    total = await session.scalar(select(func.count(Referral.id))) or 0
    rewarded = (
        await session.scalar(
            select(func.count(Referral.id)).where(Referral.rewarded.is_(True))
        )
        or 0
    )
    top = await session.execute(
        select(Referral.referrer_telegram_id, func.count(Referral.id).label("cnt"))
        .group_by(Referral.referrer_telegram_id)
        .order_by(func.count(Referral.id).desc())
        .limit(10)
    )
    lines = [
        "🎫 <b>Referral-Programm</b>\n",
        f"Eingeladene Nutzer: <b>{total}</b>",
        f"Belohnte Käufe: <b>{rewarded}</b>",
        f"Belohnung: {settings.referral_reward_days} Tage/Kauf "
        f"({'aktiv' if settings.referral_enabled else 'AUS'})\n",
    ]
    rows = top.all()
    if rows:
        lines.append("Top-Werber:")
        for tg_id, cnt in rows:
            lines.append(f"• <code>{tg_id}</code> — {cnt} Einladung(en)")
    return "\n".join(lines)


_HELP_TEXT = (
    "❓ <b>Admin-Befehle</b>\n\n"
    "<b>Premium</b>\n"
    "<code>/grant &lt;id&gt; [tage]</code> — Premium schenken\n"
    "<code>/revoke &lt;id&gt;</code> — Premium beenden\n"
    "<code>/settier &lt;id&gt; &lt;free|pro|unlimited&gt;</code>\n\n"
    "<b>Rollen</b> (nur Owner)\n"
    "<code>/promote &lt;id&gt; &lt;super_admin|admin|moderator|user&gt;</code>\n\n"
    "<b>Coupons</b>\n"
    "<code>/newcoupon CODE percent=20|stars=50|days=7 [uses=N] [valid=TAGE]</code>\n"
    "<code>/coupons</code> · <code>/delcoupon CODE</code>\n\n"
    "<b>Kommunikation</b>\n"
    "<code>/broadcast</code> — Assistent: Text/Foto/Video, Zielgruppe, Button, "
    "Zeitplan, Vorschau\n"
    "<code>/broadcast &lt;text&gt;</code> — Schnellversand an alle\n"
    "<code>/broadcasts</code> — Übersicht, Statistik, geplante abbrechen\n"
    "<code>/reply &lt;id&gt; &lt;text&gt;</code> — Support-Antwort"
)


# --- Panel entry + navigation ---------------------------------------------------
@router.message(Command("admin", "dashboard"))
async def cmd_admin(message: Message, user: User, session: AsyncSession) -> None:
    if not has_role(user, UserRole.MODERATOR):
        return
    logger.info(
        "ADMIN: panel opened by {} ({})",
        user.telegram_id, effective_role(user).value,
    )
    await message.answer(await _dashboard_text(session), reply_markup=_panel_keyboard())


@router.callback_query(F.data.startswith("adminp:"))
async def cb_admin_panel(cb: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not has_role(user, UserRole.MODERATOR):
        await cb.answer("⛔ Kein Zugriff", show_alert=True)
        return
    section = cb.data.split(":")[-1]
    if section == "users":
        text = await _users_text(session)
    elif section == "payments":
        if not has_role(user, UserRole.ADMIN):
            await cb.answer("⛔ Nur für Admins", show_alert=True)
            return
        text = await _payments_text(session)
    elif section == "coupons":
        if not has_role(user, UserRole.ADMIN):
            await cb.answer("⛔ Nur für Admins", show_alert=True)
            return
        text = await _coupons_text(session)
    elif section == "referrals":
        text = await _referrals_text(session)
    elif section == "broadcasts":
        if not has_role(user, UserRole.ADMIN):
            await cb.answer("⛔ Nur für Admins", show_alert=True)
            return
        text = await _broadcasts_text(session)
    elif section == "help":
        text = _HELP_TEXT
    else:
        text = await _dashboard_text(session)

    from aiogram.exceptions import TelegramBadRequest

    try:
        await cb.message.edit_text(text, reply_markup=_panel_keyboard())
    except TelegramBadRequest:
        pass  # identical content — refresh with no changes
    await cb.answer()


# --- Roles ------------------------------------------------------------------------
@router.message(Command("promote"))
async def cmd_promote(
    message: Message, user: User, session: AsyncSession, command: CommandObject
) -> None:
    if not has_role(user, UserRole.OWNER):
        return
    args = (command.args or "").split()
    if len(args) != 2 or args[1].lower() not in ASSIGNABLE_ROLES:
        await message.answer(
            "Nutzung: <code>/promote &lt;telegram_id&gt; "
            "&lt;super_admin|admin|moderator|user&gt;</code>"
        )
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
    if effective_role(target) is UserRole.OWNER:
        await message.answer("⛔ Der Owner kann nicht verwaltet werden.")
        return
    target.role = ASSIGNABLE_ROLES[args[1].lower()]
    await session.flush()
    logger.info(
        "ADMIN: {} set role of {} to {}",
        user.telegram_id, target_id, target.role.value,
    )
    await message.answer(
        f"✅ <b>{escape(target.display_name)}</b> ist jetzt "
        f"<b>{target.role.value}</b>."
    )


# --- Tier management ---------------------------------------------------------------
@router.message(Command("settier"))
async def cmd_settier(
    message: Message, user: User, session: AsyncSession, command: CommandObject
) -> None:
    if not has_role(user, UserRole.ADMIN):
        return

    args = (command.args or "").split()
    if len(args) != 2 or args[1].lower() not in ASSIGNABLE_TIERS:
        await message.answer(
            "Nutzung: <code>/settier &lt;telegram_id&gt; "
            "&lt;free|starter|pro|dealer&gt;</code>\n"
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
    # Rules must follow the level immediately, up or down.
    paused, slowed = await premium_svc.enforce_tier_limits(session, target)
    logger.info(
        "ADMIN: {} set tier of {} to {} ({} paused, {} adjusted)",
        user.telegram_id, target_id, target.subscription.value, paused, slowed,
    )
    await message.answer(
        f"✅ <b>{escape(target.display_name)}</b> (ID {target.telegram_id}) "
        f"ist jetzt <b>{target.tier_label}</b> "
        f"(max. {target.max_rules} Suchen, {target.entitlements.fast_slots} Schnell-Slots)."
        + (f"\n⏸ {paused} Suche(n) pausiert." if paused else "")
        + (f"\n⏱ {slowed} Intervall(e) angepasst." if slowed else "")
    )


@router.message(Command("tiers", "users"))
async def cmd_tiers(message: Message, user: User, session: AsyncSession) -> None:
    if not has_role(user, UserRole.MODERATOR):
        return
    await message.answer(await _users_text(session))


# --- Premium grant / revoke ----------------------------------------------------------
@router.message(Command("grant"))
async def cmd_grant(
    message: Message, user: User, session: AsyncSession, command: CommandObject
) -> None:
    if not has_role(user, UserRole.ADMIN):
        return

    args = (command.args or "").split()
    if not args:
        await message.answer(
            "Nutzung: <code>/grant &lt;telegram_id&gt; [tage] [starter|pro|dealer]</code>"
            "\nStandard: 31 Tage, Profi."
        )
        return
    tier = SubscriptionTier.PRO
    try:
        target_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else settings.premium_period_days
        if len(args) > 2:
            tier = ASSIGNABLE_TIERS[args[2].lower()]
    except (ValueError, KeyError):
        await message.answer("⚠️ ID und Tage müssen Zahlen sein, Tarif starter|pro|dealer.")
        return
    if tier is SubscriptionTier.FREE:
        await message.answer("⚠️ Free kann man nicht schenken — dafür gibt es /revoke.")
        return

    result = await session.execute(select(User).where(User.telegram_id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        await message.answer(f"⚠️ Kein Nutzer mit ID <code>{target_id}</code>.")
        return

    sub = await premium_svc.activate_premium(
        session, target, days=days, provider="admin_grant",
        plan=PlanType.ADMIN_GRANT, tier=tier,
    )
    await premium_svc.record_payment(
        session, target, provider="admin_grant", amount_stars=0,
        subscription_id=sub.id, status="granted",
    )
    logger.info(
        "ADMIN: {} granted premium to {} for {}d",
        user.telegram_id, target_id, days,
    )
    await message.answer(
        f"✅ <b>{escape(target.display_name)}</b> hat <b>{target.tier_label}</b> bis "
        f"<b>{sub.subscription_end:%d.%m.%Y}</b>."
    )


@router.message(Command("revoke"))
async def cmd_revoke(
    message: Message, user: User, session: AsyncSession, command: CommandObject
) -> None:
    if not has_role(user, UserRole.ADMIN):
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
    logger.info("ADMIN: {} revoked premium of {}", user.telegram_id, target_id)
    await message.answer(
        f"✅ Premium von <b>{escape(target.display_name)}</b> beendet (jetzt Free)."
    )


# --- Coupon management ----------------------------------------------------------------
@router.message(Command("newcoupon"))
async def cmd_newcoupon(
    message: Message, user: User, session: AsyncSession, command: CommandObject
) -> None:
    if not has_role(user, UserRole.ADMIN):
        return
    args = (command.args or "").split()
    if not args:
        await message.answer(
            "Nutzung: <code>/newcoupon CODE percent=20|stars=50|days=7 "
            "[uses=N] [valid=TAGE]</code>"
        )
        return

    code = args[0]
    params: dict[str, int] = {}
    for token in args[1:]:
        if "=" not in token:
            continue
        key, _, raw = token.partition("=")
        try:
            params[key.lower()] = int(raw)
        except ValueError:
            await message.answer(f"⚠️ Ungültiger Wert: <code>{escape(token)}</code>")
            return

    valid_until = None
    if "valid" in params:
        valid_until = datetime.now(timezone.utc) + timedelta(days=params["valid"])

    try:
        coupon = await coupon_svc.create_coupon(
            session,
            code=code,
            created_by=user.telegram_id,
            discount_percent=params.get("percent"),
            discount_fixed_stars=params.get("stars"),
            free_days=params.get("days"),
            max_uses=params.get("uses"),
            valid_until=valid_until,
        )
    except coupon_svc.CouponError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    logger.info("ADMIN: {} created coupon {}", user.telegram_id, coupon.code)
    await message.answer(
        f"✅ Coupon <code>{coupon.code}</code> angelegt!\n"
        f"Nutzer lösen ihn ein mit: <code>/coupon {coupon.code}</code>"
    )


@router.message(Command("coupons"))
async def cmd_coupons(message: Message, user: User, session: AsyncSession) -> None:
    if not has_role(user, UserRole.ADMIN):
        return
    await message.answer(await _coupons_text(session))


@router.message(Command("delcoupon"))
async def cmd_delcoupon(
    message: Message, user: User, session: AsyncSession, command: CommandObject
) -> None:
    if not has_role(user, UserRole.ADMIN):
        return
    code = (command.args or "").strip().upper()
    if not code:
        await message.answer("Nutzung: <code>/delcoupon CODE</code>")
        return
    coupon = await coupon_svc.get_coupon(session, code)
    if coupon is None:
        await message.answer(f"⚠️ Coupon <code>{escape(code)}</code> nicht gefunden.")
        return
    coupon.is_active = False
    await session.flush()
    logger.info("ADMIN: {} deactivated coupon {}", user.telegram_id, code)
    await message.answer(f"✅ Coupon <code>{coupon.code}</code> deaktiviert.")


# Broadcasts live in app/bot/handlers/broadcast.py (wizard, media, scheduling).
