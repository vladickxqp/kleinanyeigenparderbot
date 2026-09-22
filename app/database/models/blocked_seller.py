"""Sellers a user never wants to hear from again.

The 🙈 button hides one ad. A dealer with two hundred cars on AutoScout24, or
anyone who posts the same thing under new ids faster than the repost window
closes, needs the seller silenced rather than the ad.

Keyed on the marketplace's own seller id wherever it has one, because a dealer
can rename itself overnight and a block that follows the name would quietly
stop working. Only the sites that actually name a seller can be blocked; the
rest never reach this table, which is why nothing here is presented as a
guarantee across all marketplaces.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PKMixin, TimestampMixin
from app.database.models.enums import SiteName


class BlockedSeller(Base, PKMixin, TimestampMixin):
    """One seller one user does not want to see."""

    __table_args__ = (
        UniqueConstraint("user_id", "site", "seller_key", name="uq_blocked_seller"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    site: Mapped[SiteName] = mapped_column(String(24), nullable=False)
    #: The marketplace's seller id, or the folded name when it has no id.
    seller_key: Mapped[str] = mapped_column(String(128), nullable=False)
    #: What to show the user in the list — the name as it was when blocked.
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BlockedSeller user={self.user_id} {self.site}:{self.seller_key}>"
