"""Subscription model — the payment lifecycle behind a user's premium tier.

``User.subscription`` stays the *effective* tier used for fast permission
checks; this table records how that tier came to be (payments, grants,
expiry). One user can accumulate multiple rows over time (history).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PKMixin, TimestampMixin


class PlanType(str, enum.Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"          # future-proof: not offered yet
    ADMIN_GRANT = "admin_grant"
    TRIAL = "trial"
    REFERRAL = "referral"      # reward days for successful referrals
    COUPON = "coupon"          # free days granted by a coupon


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELED = "canceled"
    SUSPENDED = "suspended"


class Subscription(Base, PKMixin, TimestampMixin):
    """One premium period of a user (created/extended per payment or grant)."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    #: Denormalised for quick admin lookups without a join.
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, length=16),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    plan_type: Mapped[PlanType] = mapped_column(
        Enum(PlanType, native_enum=False, length=16),
        default=PlanType.MONTHLY,
        nullable=False,
    )

    subscription_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    subscription_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    #: For auto-renewing plans this equals subscription_end.
    renewal_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    payment_provider: Mapped[str] = mapped_column(
        String(32), default="telegram_stars", nullable=False
    )
    payment_status: Mapped[str] = mapped_column(
        String(32), default="paid", nullable=False
    )
    #: Telegram's charge id of the LAST payment on this subscription.
    telegram_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Which level this subscription grants. Without it every renewal had to
    #: guess the tier and could silently upgrade a cheaper plan.
    tier: Mapped[str] = mapped_column(
        String(16), default="unlimited", server_default="unlimited", nullable=False
    )
    #: Price actually paid per period (Stars) and its EUR equivalent.
    price_stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: Number of successful charges booked onto this subscription.
    payments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Subscription id={self.id} tg={self.telegram_id} "
            f"{self.status.value} until {self.subscription_end:%Y-%m-%d}>"
        )
