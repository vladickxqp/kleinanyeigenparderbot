"""Coupon engine models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PKMixin, TimestampMixin


class Coupon(Base, PKMixin, TimestampMixin):
    """A discount / free-days code. Exactly ONE benefit field should be set."""

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    #: Benefit — exactly one of these is non-null/positive.
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_fixed_stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: None = unlimited activations.
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Coupon {self.code} used={self.used_count}/{self.max_uses}>"


class CouponRedemption(Base, PKMixin, TimestampMixin):
    """Tracks who redeemed which coupon (each code once per user)."""

    __table_args__ = (
        UniqueConstraint("coupon_id", "telegram_id", name="uq_coupon_user"),
    )

    coupon_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("coupons.id", ondelete="CASCADE"), index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
