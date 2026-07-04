"""SearchRule model — a user's saved search / filter configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, PKMixin, TimestampMixin
from app.database.models.enums import Condition, SiteName

if TYPE_CHECKING:
    from app.database.models.listing import Listing
    from app.database.models.user import User


class SearchRule(Base, PKMixin, TimestampMixin):
    """A single, fully-configurable search a user wants the bot to run."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Human-friendly name shown in the UI, e.g. "RTX 4090 under 1300€".
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # --- Core query ---------------------------------------------------------
    keywords: Mapped[str] = mapped_column(String(256), nullable=False)
    exclude_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Price / condition --------------------------------------------------
    min_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition: Mapped[Condition] = mapped_column(
        Enum(Condition, native_enum=False, length=16),
        default=Condition.ANY,
        nullable=False,
    )

    # --- Location -----------------------------------------------------------
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    max_distance_km: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Seller / shipping constraints -------------------------------------
    min_seller_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_shipping_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    shipping_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exclude_auctions: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Which sites to search (empty = all registered parsers) -------------
    sites: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    # --- Scheduling ---------------------------------------------------------
    interval_seconds: Mapped[int] = mapped_column(
        Integer, default=300, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Only notify when the deal is at least this good (0-100 heuristic/AI score).
    min_deal_score: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    # --- Relationships ------------------------------------------------------
    user: Mapped["User"] = relationship(back_populates="search_rules")
    listings: Mapped[list["Listing"]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    @property
    def target_sites(self) -> list[SiteName]:
        """Resolve configured site strings to SiteName; empty means 'all'."""
        result: list[SiteName] = []
        for s in self.sites:
            try:
                result.append(SiteName(s))
            except ValueError:
                continue
        return result

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SearchRule id={self.id} name={self.name!r} kw={self.keywords!r}>"
