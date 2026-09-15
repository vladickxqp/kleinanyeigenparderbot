"""Payment model — one row per individual charge (full payment history).

The ``subscriptions`` table tracks the CURRENT entitlement; this table is the
immutable ledger: every Stars charge, renewal and admin grant lands here.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PKMixin, TimestampMixin


class Payment(Base, PKMixin, TimestampMixin):
    """A single (attempted) charge, kept forever for accounting."""

    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    subscription_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    #: Provider module that processed the charge ("telegram_stars", later
    #: "stripe", "paypal", ...). New providers only add a new string value.
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount_stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="XTR", nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default="paid", nullable=False, index=True
    )
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_renewal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Telegram charge id / future provider transaction id. Unique so a
    #: redelivered ``successful_payment`` update can never be booked twice.
    charge_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    #: The invoice payload, e.g. "premium_monthly" or "premium_monthly:CODE".
    invoice_payload: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Coupon code applied to this charge, if any.
    coupon_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Payment id={self.id} tg={self.telegram_id} "
            f"{self.amount_stars}⭐ {self.status}>"
        )
