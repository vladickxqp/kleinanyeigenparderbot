"""Flip model — an item the user actually bought (and maybe resold).

Turns the bot from a deal finder into a profit tracker: every purchase is
recorded with its price, every sale closes the flip with fees and net profit,
and /profit aggregates the real numbers instead of estimates.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PKMixin, TimestampMixin


class FlipStatus(str, enum.Enum):
    BOUGHT = "bought"      # in inventory, waiting to be resold
    SOLD = "sold"
    CANCELED = "canceled"  # purchase fell through / logged by mistake


class Flip(Base, PKMixin, TimestampMixin):
    """One bought item and, once resold, its realised result."""

    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    #: The deal card it came from (kept even if the listing is deleted later).
    listing_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    buy_price: Mapped[float] = mapped_column(Float, nullable=False)
    sell_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Marketplace fees + shipping deducted at sale time (configured rates).
    fees_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: sell_price − fees − buy_price; None while still in inventory.
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[FlipStatus] = mapped_column(
        Enum(FlipStatus, native_enum=False, length=16),
        default=FlipStatus.BOUGHT,
        nullable=False,
        index=True,
    )
    bought_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sold_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Flip id={self.id} {self.status.value} buy={self.buy_price}>"
