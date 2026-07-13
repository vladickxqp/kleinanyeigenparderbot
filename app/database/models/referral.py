"""Referral model — who invited whom, and whether the reward was paid out."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PKMixin, TimestampMixin


class Referral(Base, PKMixin, TimestampMixin):
    """One row per invited user (a user can only ever be referred once)."""

    referrer_telegram_id: Mapped[int] = mapped_column(
        BigInteger, index=True, nullable=False
    )
    referred_telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    #: Set once the referred user's first payment triggered the reward.
    rewarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
