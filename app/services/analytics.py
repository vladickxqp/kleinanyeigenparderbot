"""Business metrics: recurring revenue, churn, conversion.

Lifetime totals cannot answer the only question that matters month to month —
is this growing or shrinking. These are the numbers a one-person SaaS actually
steers by, computed straight from the payment ledger and subscription table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Payment,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)

WINDOW_DAYS = 30


@dataclass(slots=True)
class BusinessMetrics:
    active_subs: int
    new_subs: int
    churned: int
    churn_percent: float
    revenue_30d: float
    revenue_prev_30d: float
    arpu: float
    trials_started: int
    trials_converted: int
    trial_conversion_percent: float
    paying_users: int

    @property
    def revenue_trend_percent(self) -> float | None:
        if self.revenue_prev_30d <= 0:
            return None
        delta = self.revenue_30d - self.revenue_prev_30d
        return round(delta / self.revenue_prev_30d * 100, 1)


async def business_metrics(
    session: AsyncSession, now: datetime | None = None
) -> BusinessMetrics:
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)
    prev_start = now - timedelta(days=WINDOW_DAYS * 2)

    async def count(stmt) -> int:
        return int(await session.scalar(stmt) or 0)

    async def total(stmt) -> float:
        return float(await session.scalar(stmt) or 0.0)

    active_subs = await count(
        select(func.count(Subscription.id)).where(
            Subscription.status == SubscriptionStatus.ACTIVE
        )
    )
    new_subs = await count(
        select(func.count(Subscription.id)).where(
            Subscription.subscription_start >= window_start
        )
    )
    churned = await count(
        select(func.count(Subscription.id)).where(
            Subscription.status.in_(
                [SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELED]
            ),
            Subscription.subscription_end >= window_start,
            Subscription.subscription_end <= now,
        )
    )
    paying_users = await count(
        select(func.count(User.id)).where(User.subscription != SubscriptionTier.FREE)
    )

    revenue_30d = await total(
        select(func.coalesce(func.sum(Payment.amount_eur), 0.0)).where(
            Payment.status == "paid",
            Payment.refunded.is_(False),
            Payment.created_at >= window_start,
        )
    )
    revenue_prev_30d = await total(
        select(func.coalesce(func.sum(Payment.amount_eur), 0.0)).where(
            Payment.status == "paid",
            Payment.refunded.is_(False),
            Payment.created_at >= prev_start,
            Payment.created_at < window_start,
        )
    )

    trials_started = await count(
        select(func.count(Payment.id)).where(Payment.provider == "trial")
    )
    # Converted = the user ran a trial and later paid for real.
    trial_users = select(Payment.telegram_id).where(Payment.provider == "trial")
    trials_converted = await count(
        select(func.count(func.distinct(Payment.telegram_id))).where(
            Payment.provider == "telegram_stars",
            Payment.status == "paid",
            Payment.telegram_id.in_(trial_users),
        )
    )

    # Churn against the population that existed at the start of the window.
    base = active_subs + churned
    return BusinessMetrics(
        active_subs=active_subs,
        new_subs=new_subs,
        churned=churned,
        churn_percent=round(churned / base * 100, 1) if base else 0.0,
        revenue_30d=round(revenue_30d, 2),
        revenue_prev_30d=round(revenue_prev_30d, 2),
        arpu=round(revenue_30d / paying_users, 2) if paying_users else 0.0,
        trials_started=trials_started,
        trials_converted=trials_converted,
        trial_conversion_percent=(
            round(trials_converted / trials_started * 100, 1) if trials_started else 0.0
        ),
        paying_users=paying_users,
    )


def format_metrics(m: BusinessMetrics) -> str:
    """HTML block for the admin dashboard."""
    trend = m.revenue_trend_percent
    if trend is None:
        trend_text = ""
    elif trend >= 0:
        trend_text = f" (📈 +{trend}%)"
    else:
        trend_text = f" (📉 {trend}%)"

    return (
        "💼 <b>Geschäft (30 Tage)</b>\n"
        f"💶 Umsatz: <b>{m.revenue_30d:.2f} €</b>{trend_text}\n"
        f"🔁 Aktive Abos: <b>{m.active_subs}</b> · neu: {m.new_subs} · "
        f"verloren: {m.churned}\n"
        f"📉 Churn: <b>{m.churn_percent}%</b> · ARPU: {m.arpu:.2f} €\n"
        f"🆓 Tests: {m.trials_started} → gekauft: {m.trials_converted} "
        f"(<b>{m.trial_conversion_percent}%</b>)"
    )
