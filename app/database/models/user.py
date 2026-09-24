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

    #: Channel or group every delivered deal card is copied to (Händler
    #: feature). Kept across a downgrade; ``services.forwarding`` decides
    #: whether it is currently in effect.
    forward_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Relationships. lazy="noload": nothing reads these collections directly
    # (repositories query explicitly), and eager selectin loading added two
    # extra queries to EVERY user lookup — i.e. to every Telegram update.
    search_rules: Mapped[list["SearchRule"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or str(self.telegram_id)

    @property
    def is_paid_tier(self) -> bool:
        """True for any tier above Free (paid or admin-granted)."""
        return self.subscription is not SubscriptionTier.FREE

    @property
    def entitlements(self):
        """Everything this user's level allows (see services.entitlements)."""
        from app.services.entitlements import for_tier

        return for_tier(self.subscription)

    @property
    def tier_label(self) -> str:
        return self.entitlements.label

    @property
    def max_rules(self) -> int:
        """Rule quota of the user's level."""
        return self.entitlements.max_rules

    @property
    def min_interval_seconds(self) -> int:
        """Fastest interval a fast-slot rule may run at."""
        return self.entitlements.interval_floor(fast=True)

    @property
    def base_interval_seconds(self) -> int:
        """Interval floor for rules outside the fast slots."""
        return self.entitlements.interval_floor(fast=False)

    def has_feature(self, feature: str) -> bool:
        return self.entitlements.has(feature)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} tg={self.telegram_id} {self.display_name!r}>"
