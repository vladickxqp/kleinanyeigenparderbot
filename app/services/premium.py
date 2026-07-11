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


async def create_invoice_link() -> str | None:
    """Create a Telegram Stars subscription invoice link (or None on failure)."""
    payload = {
        "title": "Deal Hunter Premium",
        "description": (
            "Unbegrenzte Suchen, schnellstes Prüf-Intervall und Prioritäts-"
            "Verarbeitung. Monatlich, jederzeit kündbar."
        ),
        "payload": "premium_monthly",
        "currency": "XTR",
        "prices": [{"label": "Premium (1 Monat)", "amount": settings.premium_price_stars}],
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
