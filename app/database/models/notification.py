"""Notification model — an outbound message sent (or queued) to a user."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, PKMixin, TimestampMixin
from app.database.models.enums import NotificationChannel

if TYPE_CHECKING:
    from app.database.models.user import User


class Notification(Base, PKMixin, TimestampMixin):
    """Record of a notification delivery attempt for auditing/history."""

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=16),
        default=NotificationChannel.TELEGRAM,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="notifications")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Notification id={self.id} user={self.user_id} sent={self.is_sent}>"
