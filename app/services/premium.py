"""Premium subscription lifecycle (Telegram Stars).

Why Telegram Stars: recurring card payments (Stripe & Co.) require a public
HTTPS webhook endpoint, which a long-polling home deployment does not have.
Stars subscriptions run entirely inside Telegram: the invoice link carries
``subscription_period``, Telegram auto-charges every month and delivers each
charge as a fresh ``successful_payment`` update over the normal polling
connection. Cancelling is done by the user in Telegram's own subscription
settings — the charges simply stop and the subscription expires here.

The invoice link is created via a direct Bot API call instead of the aiogram
helper because the pinned aiogram version predates the ``subscription_period``
parameter; the raw call is version-proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import (
    Payment,
    PlanType,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)

#: Fixed by the Bot API: the only supported Stars subscription period (30 days).
TELEGRAM_SUBSCRIPTION_PERIOD = 2_592_000


def stars_to_eur(amount_stars: int) -> float:
    """Convert a Stars amount to euros at the one ledger-wide rate."""
    if amount_stars <= 0 or settings.stars_per_eur <= 0:
        return 0.0
    return round(amount_stars / settings.stars_per_eur, 2)


@dataclass(frozen=True, slots=True)
class Plan:
    """One purchasable subscription level."""

    key: str
    label: str
    tier: SubscriptionTier
    price_stars: int
    price_eur: float
    max_rules: int
    min_interval_seconds: int
    description: str

    @property
    def entitlements(self):
        from app.services.entitlements import for_tier

        return for_tier(self.tier)


def _describe(tier: SubscriptionTier) -> str:
    from app.services.entitlements import fmt_quota, for_tier

    e = for_tier(tier)
    fast = (
        f"{e.fast_slots} Schnell-Slots im {e.min_interval_seconds // 60}-Minuten-Takt, "
        if e.fast_slots
        else ""
    )
    return (
        f"{e.max_rules} Suchen, {fast}"
        f"{fmt_quota(e.daily_notifications, ' Karten/Tag')}, "
        f"{fmt_quota(e.photo_evals_per_month, ' Foto-Bewertungen/Monat')}."
    )


def _plan(key: str, tier: SubscriptionTier, stars: int, eur: float) -> Plan:
    from app.services.entitlements import for_tier

    e = for_tier(tier)
    return Plan(
        key=key,
        label=e.label,
        tier=tier,
        price_stars=stars,
        price_eur=eur,
        max_rules=e.max_rules,
        min_interval_seconds=e.min_interval_seconds,
        description=_describe(tier),
    )


def all_plans() -> list[Plan]:
    """Every paid level, cheapest first, whether or not it is on sale."""
    return [
        _plan("starter", SubscriptionTier.STARTER,
              settings.starter_price_stars, settings.starter_price_eur),
        _plan("pro", SubscriptionTier.PRO,
              settings.pro_price_stars, settings.pro_price_eur),
        _plan("dealer", SubscriptionTier.UNLIMITED,
              settings.dealer_price_stars, settings.dealer_price_eur),
    ]


def dealer_on_sale() -> bool:
    """The Händler plan needs a proxy pool: one dealer at full speed generates
    more requests per minute than a single home IP can carry."""
    if not settings.dealer_requires_proxies:
        return True
    return bool(settings.proxy_list)


def available_plans() -> list[Plan]:
    """The plans on sale right now, cheapest first."""
    return [p for p in all_plans() if p.key != "dealer" or dealer_on_sale()]


def trial_tier() -> SubscriptionTier:
    """Which level the free trial grants (configurable, never the top one by
    default: trial accounts consume the same scarce request budget)."""
    try:
        return SubscriptionTier(settings.trial_tier).canonical
    except ValueError:
        return SubscriptionTier.PRO


#: Legacy payload keys from links issued before the ladder existed.
_LEGACY_PLAN_KEYS = {"unlimited": "dealer", "premium": "pro", "ultimate": "dealer"}


def plan_by_key(key: str) -> Plan:
    """Look a plan up. Unknown keys fall back to the CHEAPEST plan — a broken
    payload must never upgrade anyone to the most expensive level."""
    key = _LEGACY_PLAN_KEYS.get(key, key)
    plans = {p.key: p for p in all_plans()}
    return plans.get(key, plans["starter"])


def plan_for_tier(tier: SubscriptionTier) -> Plan:
    for plan in all_plans():
        if plan.tier is tier.canonical:
            return plan
    return plan_by_key("starter")


def plan_for_payload(payload: str) -> Plan:
    """Which plan an invoice payload refers to ("premium_monthly:pro:CODE")."""
    parts = payload.split(":")
    if len(parts) > 1:
        candidate = _LEGACY_PLAN_KEYS.get(parts[1], parts[1])
        if candidate in {p.key for p in all_plans()}:
            return plan_by_key(candidate)
    return plan_by_key("starter")


async def create_invoice_link(
    *,
    price_stars: int | None = None,
    coupon_code: str | None = None,
    plan_key: str = "unlimited",
) -> str | None:
    """Create a Telegram Stars subscription invoice link (or None on failure).

    ``price_stars`` overrides the plan price (coupon discounts). The plan and
    the coupon code travel in the payload, so the successful payment grants the
    right tier and books the redemption only when money actually flowed.
    """
    plan = plan_by_key(plan_key)
    amount = price_stars or plan.price_stars
    invoice_payload = f"premium_monthly:{plan.key}"
    if coupon_code:
        invoice_payload += f":{coupon_code}"
    payload = {
        "title": f"Deal Hunter {plan.label}",
        "description": plan.description + " Monatlich, jederzeit kündbar.",
        "payload": invoice_payload,
        "currency": "XTR",
        "prices": [{"label": f"{plan.label} (1 Monat)", "amount": amount}],
        "subscription_period": TELEGRAM_SUBSCRIPTION_PERIOD,
    }
    url = f"https://api.telegram.org/bot{settings.bot_token}/createInvoiceLink"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
        if data.get("ok"):
            return str(data["result"])
        logger.error("createInvoiceLink failed: {}", data)
    except Exception as exc:  # noqa: BLE001
        logger.error("createInvoiceLink error: {}", exc)
    return None


#: payment_status value for "cancelled, but paid period still running".
CANCEL_AT_PERIOD_END = "cancel_at_period_end"


async def cancel_stars_subscription(telegram_id: int, charge_id: str) -> bool:
    """Stop the auto-renewal of a Stars subscription via the Bot API.

    Uses ``editUserStarSubscription`` (Bot API 8.0) as a raw call, immune to
    the pinned aiogram version. The user keeps premium until the already-paid
    period ends; Telegram simply won't charge again, and the nightly expiry
    sweep downgrades the account afterwards.
    """
    url = f"https://api.telegram.org/bot{settings.bot_token}/editUserStarSubscription"
    payload = {
        "user_id": telegram_id,
        "telegram_payment_charge_id": charge_id,
        "is_canceled": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
        if data.get("ok"):
            logger.info("PREMIUM: renewal cancelled for {} ({})", telegram_id, charge_id)
            return True
        logger.error("editUserStarSubscription failed: {}", data)
    except Exception as exc:  # noqa: BLE001
        logger.error("editUserStarSubscription error: {}", exc)
    return False


async def get_active_subscription(
    session: AsyncSession, telegram_id: int
) -> Subscription | None:
    """The user's current ACTIVE subscription row, if any."""
    result = await session.execute(
        select(Subscription)
        .where(
            Subscription.telegram_id == telegram_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.subscription_end.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def charge_already_processed(session: AsyncSession, charge_id: str) -> bool:
    """True when this provider charge was already booked.

    Telegram can redeliver a ``successful_payment`` update (bot restart, network
    hiccup). Without this check the same money would extend the subscription a
    second time and show up twice in the ledger.
    """
    if not charge_id:
        return False
    result = await session.execute(
        select(Payment.id).where(Payment.charge_id == charge_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def activate_premium(
    session: AsyncSession,
    user: User,
    *,
    days: int | None = None,
    provider: str = "telegram_stars",
    plan: PlanType = PlanType.MONTHLY,
    charge_id: str | None = None,
    price_stars: int | None = None,
    tier: SubscriptionTier | None = None,
) -> Subscription:
    """Grant or extend premium for ``user`` and set the effective tier.

    Called for the first purchase, every automatic renewal charge and admin
    grants alike: an existing active subscription is extended, otherwise a new
    row is created.
    """
    days = days or settings.premium_period_days
    now = datetime.now(timezone.utc)

    sub = await get_active_subscription(session, user.telegram_id)
    if sub is not None:
        base = max(sub.subscription_end, now)
        sub.subscription_end = base + timedelta(days=days)
        sub.renewal_date = sub.subscription_end
        sub.payments_count += 1
        sub.payment_status = "paid"
        if charge_id:
            sub.telegram_charge_id = charge_id
        # A renewal without an explicit tier keeps the level that was bought;
        # an explicit higher tier (upgrade purchase) wins.
        stored = _tier_from_string(sub.tier)
        if tier is None:
            tier = stored
        elif stored is not None and tier.rank < stored.rank and provider == "telegram_stars":
            tier = stored
        sub.tier = (tier or SubscriptionTier.PRO).canonical.value
    else:
        tier = tier or SubscriptionTier.PRO
        sub = Subscription(
            user_id=user.id,
            telegram_id=user.telegram_id,
            status=SubscriptionStatus.ACTIVE,
            plan_type=plan,
            subscription_start=now,
            subscription_end=now + timedelta(days=days),
            renewal_date=now + timedelta(days=days),
            payment_provider=provider,
            payment_status="paid" if provider == "telegram_stars" else "granted",
            telegram_charge_id=charge_id,
            tier=tier.canonical.value,
            price_stars=price_stars or 0,
            price_eur=stars_to_eur(price_stars or 0),
            payments_count=1 if charge_id else 0,
        )
        session.add(sub)

    # Never silently downgrade a user who holds a higher level from a grant.
    new_tier = (tier or SubscriptionTier.PRO).canonical
    if user.subscription.canonical.rank < new_tier.rank or not user.is_paid_tier:
        user.subscription = new_tier
    await session.flush()
    await enforce_tier_limits(session, user)
    logger.info(
        "PREMIUM: {} active until {} as {} (provider={}, charge={})",
        user.telegram_id, sub.subscription_end, user.subscription.value,
        provider, charge_id,
    )
    return sub


async def deactivate_premium(
    session: AsyncSession,
    user: User,
    *,
    status: SubscriptionStatus = SubscriptionStatus.CANCELED,
) -> None:
    """End the user's premium immediately (admin action or refund)."""
    sub = await get_active_subscription(session, user.telegram_id)
    if sub is not None:
        sub.status = status
        sub.payment_status = status.value
    user.subscription = SubscriptionTier.FREE
    await session.flush()
    await enforce_tier_limits(session, user)
    logger.info("PREMIUM: {} deactivated ({})", user.telegram_id, status.value)


def _tier_from_string(value: str | None) -> SubscriptionTier | None:
    try:
        return SubscriptionTier(value).canonical if value else None
    except ValueError:
        return None


async def enforce_tier_limits(session: AsyncSession, user: User) -> tuple[int, int]:
    """Bring a user's rules back in line with their CURRENT level.

    Three things are reconciled, oldest rules first so a downgrade never
    silently swaps which searches keep running:

    * at most ``max_rules`` rules stay active;
    * at most ``fast_slots`` rules may run below the base interval, and those
      may not go under the tier's fast floor;
    * every other rule is raised to the base interval.

    Returns how many rules were paused and how many intervals were changed.
    """
    from app.database.models import SearchRule

    e = user.entitlements
    result = await session.execute(
        select(SearchRule)
        .where(SearchRule.user_id == user.id)
        .order_by(SearchRule.created_at.asc(), SearchRule.id.asc())
    )
    rules = list(result.scalars().all())

    paused = slowed = 0
    active_seen = 0
    fast_used = 0
    fast_floor = e.interval_floor(fast=True)
    base_floor = e.interval_floor(fast=False)
    for rule in rules:
        if rule.is_active:
            active_seen += 1
            # Keep the oldest rules running, pause what exceeds the quota.
            if active_seen > e.max_rules:
                rule.is_active = False
                paused += 1

        wants_fast = rule.interval_seconds < base_floor
        if wants_fast and rule.is_active and fast_used < e.fast_slots:
            fast_used += 1
            floor = fast_floor
        else:
            floor = base_floor
        if rule.interval_seconds < floor:
            rule.interval_seconds = floor
            slowed += 1

    if paused or slowed:
        await session.flush()
        logger.info(
            "TIER: {} reconciled to {} — {} rule(s) paused, {} interval(s) adjusted",
            user.telegram_id, user.subscription.value, paused, slowed,
        )
    return paused, slowed


async def expire_overdue_subscriptions(session: AsyncSession) -> list[int]:
    """Mark overdue subscriptions as expired and downgrade their users.

    Returns the telegram ids of downgraded users (for notifications).
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.subscription_end < now,
        )
    )
    downgraded: list[int] = []
    for sub in result.scalars().all():
        sub.status = SubscriptionStatus.EXPIRED
        sub.payment_status = "expired"
        user = await session.get(User, sub.user_id)
        if user is not None and user.subscription != SubscriptionTier.FREE:
            user.subscription = SubscriptionTier.FREE
            await session.flush()
            await enforce_tier_limits(session, user)
            downgraded.append(user.telegram_id)
        logger.info("PREMIUM: subscription {} expired (tg {})", sub.id, sub.telegram_id)
    await session.flush()
    return downgraded


async def record_payment(
    session: AsyncSession,
    user: User,
    *,
    provider: str,
    amount_stars: int = 0,
    amount_eur: float = 0.0,
    currency: str = "XTR",
    charge_id: str | None = None,
    invoice_payload: str | None = None,
    coupon_code: str | None = None,
    subscription_id: int | None = None,
    is_renewal: bool = False,
    status: str = "paid",
):
    """Append one charge to the immutable payment ledger."""
    from app.database.models import Payment

    payment = Payment(
        telegram_id=user.telegram_id,
        user_id=user.id,
        subscription_id=subscription_id,
        provider=provider,
        amount_stars=amount_stars,
        amount_eur=amount_eur,
        currency=currency,
        status=status,
        charge_id=charge_id,
        invoice_payload=invoice_payload,
        coupon_code=coupon_code,
        is_renewal=is_renewal,
    )
    session.add(payment)
    await session.flush()
    return payment


async def has_used_trial(session: AsyncSession, telegram_id: int) -> bool:
    """True if this user ever activated the free trial (allowed exactly once)."""
    result = await session.execute(
        select(Subscription).where(
            Subscription.telegram_id == telegram_id,
            Subscription.plan_type == PlanType.TRIAL,
        )
    )
    return result.scalar_one_or_none() is not None


async def payments_count_for_user(session: AsyncSession, telegram_id: int) -> int:
    """Number of real (paid) charges of this user — used for referral rewards."""
    from sqlalchemy import func

    from app.database.models import Payment

    return (
        await session.scalar(
            select(func.count(Payment.id)).where(
                Payment.telegram_id == telegram_id,
                Payment.status == "paid",
                Payment.provider == "telegram_stars",
            )
        )
        or 0
    )


# --- User-facing billing: history, charge dates, refunds --------------------------------
async def payment_history(session: AsyncSession, telegram_id: int, limit: int = 12):
    """The user's own payment ledger, newest first (all providers, incl. refunds)."""
    from app.database.models import Payment

    result = await session.execute(
        select(Payment)
        .where(Payment.telegram_id == telegram_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@dataclass(slots=True)
class BillingInfo:
    """When money was last taken and when Telegram will charge next."""

    payments_count: int
    last_charge_at: datetime | None
    last_amount_stars: int | None
    next_charge_at: datetime | None


async def billing_info(session: AsyncSession, telegram_id: int) -> BillingInfo:
    """Derived from the ledger, so the dates are the REAL charge timestamps.

    Telegram bills Stars subscriptions every 30 days (the API's only period),
    so the next charge is the last successful one plus 30 days — regardless
    of the grace days the entitlement itself may carry.
    """
    from sqlalchemy import func

    from app.database.models import Payment

    paid = (
        Payment.telegram_id == telegram_id,
        Payment.provider == "telegram_stars",
        Payment.status == "paid",
    )
    count = await session.scalar(select(func.count(Payment.id)).where(*paid)) or 0
    last = (
        await session.execute(
            select(Payment).where(*paid).order_by(Payment.created_at.desc(), Payment.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if last is None:
        return BillingInfo(0, None, None, None)
    next_at = last.created_at + timedelta(seconds=TELEGRAM_SUBSCRIPTION_PERIOD)
    return BillingInfo(int(count), last.created_at, last.amount_stars, next_at)


async def mark_refunded(session: AsyncSession, telegram_id: int, charge_id: str):
    """Flag a charge as refunded (Telegram ``refunded_payment`` update)."""
    from app.database.models import Payment

    payment = (
        await session.execute(
            select(Payment).where(
                Payment.telegram_id == telegram_id, Payment.charge_id == charge_id
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        return None
    payment.refunded = True
    payment.status = "refunded"
    await session.flush()
    logger.info("PREMIUM: charge {} of {} refunded", charge_id, telegram_id)
    return payment
