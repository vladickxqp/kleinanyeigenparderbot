"""PriceHistory model — time series of an item's price for trend/graphing."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, PKMixin

if TYPE_CHECKING:
    from app.database.models.listing import Listing


class PriceHistory(Base, PKMixin):
    """A single observed price point for a listing at a moment in time."""

    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    listing: Mapped["Listing"] = relationship(back_populates="price_history")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PriceHistory listing={self.listing_id} price={self.price}>"
