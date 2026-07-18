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

from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import (
    PlanType,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)

#: Fixed by the Bot API: the only supported Stars subscription period (30 days).
TELEGRAM_SUBSCRIPTION_PERIOD = 2_592_000


async def create_invoice_link(
    *, price_stars: int | None = None, coupon_code: str | None = None
) -> str | None:
    """Create a Telegram Stars subscription invoice link (or None on failure).

    ``price_stars`` overrides the configured price (coupon discounts); the
    coupon code travels in the payload so the successful payment can be
    attributed and the redemption booked only when money actually flowed.
    """
    amount = price_stars or settings.premium_price_stars
    invoice_payload = "premium_monthly"
    if coupon_code:
        invoice_payload += f":{coupon_code}"
    payload = {
        "title": "Deal Hunter Premium",
        "description": (
            "Unbegrenzte Suchen, schnellstes Prüf-Intervall und Prioritäts-"
            "Verarbeitung. Monatlich, jederzeit kündbar."
        ),
        "payload": invoice_payload,
        "currency": "XTR",
        "prices": [{"label": "Premium (1 Monat)", "amount": amount}],
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


async def activate_premium(
    session: AsyncSession,
    user: User,
    *,
    days: int | None = None,
    provider: str = "telegram_stars",
    plan: PlanType = PlanType.MONTHLY,
    charge_id: str | None = None,
    price_stars: int | None = None,
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
    else:
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
            price_stars=price_stars or 0,
            price_eur=settings.premium_price_eur if price_stars else 0.0,
            payments_count=1 if charge_id else 0,
        )
        session.add(sub)

    user.subscription = SubscriptionTier.UNLIMITED
    await session.flush()
    logger.info(
        "PREMIUM: {} active until {} (provider={}, charge={})",
        user.telegram_id, sub.subscription_end, provider, charge_id,
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
    logger.info("PREMIUM: {} deactivated ({})", user.telegram_id, status.value)


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
        if user is not None and user.subscription in (
            SubscriptionTier.UNLIMITED, SubscriptionTier.ULTIMATE
        ):
            user.subscription = SubscriptionTier.FREE
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
