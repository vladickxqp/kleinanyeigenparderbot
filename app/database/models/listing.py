"""Listing model — a single item found by a parser for a search rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, PKMixin, TimestampMixin
from app.database.models.enums import Condition, DealVerdict, SiteName

if TYPE_CHECKING:
    from app.database.models.price_history import PriceHistory
    from app.database.models.search_rule import SearchRule


class Listing(Base, PKMixin, TimestampMixin):
    """A parsed offer. ``fingerprint`` is used to deduplicate across parsers."""

    __table_args__ = (
        UniqueConstraint("rule_id", "fingerprint", name="uq_listing_rule_fingerprint"),
        Index("ix_listing_site_external", "site", "external_id"),
    )

    rule_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("search_rules.id", ondelete="CASCADE"), index=True
    )

    site: Mapped[SiteName] = mapped_column(
        Enum(SiteName, native_enum=False, length=24), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Stable hash of normalised title+price+site used for dedup.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    shipping_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    condition: Mapped[Condition] = mapped_column(
        Enum(Condition, native_enum=False, length=16),
        default=Condition.ANY,
        nullable=False,
    )
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: The marketplace's own seller id, where it has one — what a block
    #: is keyed on, because a dealer can rename itself.
    seller_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seller_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_auction: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: "VB" — the seller marked the price as negotiable.
    is_negotiable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    # --- Deal analysis results ---------------------------------------------
    deal_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deal_verdict: Mapped[DealVerdict] = mapped_column(
        Enum(DealVerdict, native_enum=False, length=16),
        default=DealVerdict.UNKNOWN,
        nullable=False,
    )
    estimated_market_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: When the ad went online on the marketplace (None = unknown/promoted).
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Delivery bookkeeping ----------------------------------------------
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: When the card reached the user; with posted_at this is the honest
    #: "found X minutes after posting" figure on every card.
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Held back by the daily card quota (never re-delivered by the sweep).
    withheld: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_ignored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Relationships ------------------------------------------------------
    rule: Mapped["SearchRule"] = relationship(back_populates="listings")
    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    @property
    def total_price(self) -> float | None:
        if self.price is None:
            return None
        return self.price + (self.shipping_cost or 0.0)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Listing id={self.id} site={self.site.value} "
            f"price={self.price} score={self.deal_score}>"
        )
