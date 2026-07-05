"""User model — a Telegram user of the bot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, PKMixin, TimestampMixin
from app.database.models.enums import SubscriptionTier, UserRole

if TYPE_CHECKING:
    from app.database.models.notification import Notification
    from app.database.models.search_rule import SearchRule


class User(Base, PKMixin, TimestampMixin):
    """A person interacting with the bot, keyed by their Telegram id."""

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str] = mapped_column(String(8), default="de", nullable=False)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16),
        default=UserRole.USER,
        nullable=False,
    )
    subscription: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier, native_enum=False, length=16),
        default=SubscriptionTier.FREE,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    search_rules: Mapped[list["SearchRule"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or str(self.telegram_id)

    @property
    def max_rules(self) -> int:
        """Rule quota per subscription tier (Unlimited = practically no cap)."""
        return {
            SubscriptionTier.FREE: 3,
            SubscriptionTier.PRO: 25,
            SubscriptionTier.PREMIUM: 25,          # legacy = Pro
            SubscriptionTier.UNLIMITED: 1_000_000,
            SubscriptionTier.ULTIMATE: 1_000_000,  # legacy = Unlimited
        }.get(self.subscription, 3)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} tg={self.telegram_id} {self.display_name!r}>"
