"""Broadcast model — an announcement sent (or scheduled) to a user segment.

The message itself is not copied into the database: Telegram's
``copyMessage`` re-sends the admin's original message (text, photo, video,
document — formatting included) to every recipient, so we only store WHERE it
lives plus audience, optional button, schedule and delivery counters.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PKMixin, TimestampMixin


class BroadcastStatus(str, enum.Enum):
    SCHEDULED = "scheduled"   # waiting for its time (or for the next dispatcher tick)
    SENDING = "sending"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


class BroadcastAudience(str, enum.Enum):
    ALL = "all"
    FREE = "free"
    PREMIUM = "premium"


class Broadcast(Base, PKMixin, TimestampMixin):
    """One announcement with its delivery statistics."""

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    #: Source message to copy (admin's chat). Null → plain ``text`` is sent.
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Short excerpt for lists ("Sommer-Aktion: 25% auf …").
    preview: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    audience: Mapped[BroadcastAudience] = mapped_column(
        Enum(BroadcastAudience, native_enum=False, length=16),
        default=BroadcastAudience.ALL,
        nullable=False,
    )
    button_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    button_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    status: Mapped[BroadcastStatus] = mapped_column(
        Enum(BroadcastStatus, native_enum=False, length=16),
        default=BroadcastStatus.SCHEDULED,
        nullable=False,
        index=True,
    )

    #: Delivery statistics.
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Admin-side status message that receives live progress.
    status_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Broadcast id={self.id} {self.status.value} {self.sent}/{self.total}>"
