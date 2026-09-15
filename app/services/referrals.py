"""Referral system: personal invite links and first-purchase rewards.

The referral code is simply ``ref<telegram_id>`` carried as a /start deep-link
payload — no secret, no extra table for codes. A user can be referred exactly
once (unique constraint) and self-referrals are rejected. The reward (free
premium days, configurable) is paid to the inviter when the invited user's
FIRST payment succeeds.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Referral, User

REF_PREFIX = "ref"


def parse_referral_payload(payload: str | None) -> int | None:
    """Extract the referrer's telegram id from a /start deep-link payload."""
    if not payload or not payload.startswith(REF_PREFIX):
        return None
    try:
        return int(payload[len(REF_PREFIX):])
    except ValueError:
        return None


def build_referral_link(bot_username: str, telegram_id: int) -> str:
    return f"https://t.me/{bot_username}?start={REF_PREFIX}{telegram_id}"


async def register_referral(
    session: AsyncSession, referrer_tg: int, referred_tg: int
) -> bool:
    """Record that ``referred_tg`` joined via ``referrer_tg``'s link."""
    if not settings.referral_enabled or referrer_tg == referred_tg:
        return False
    existing = await session.execute(
        select(Referral).where(Referral.referred_telegram_id == referred_tg)
    )
    if existing.scalar_one_or_none() is not None:
        return False  # already referred (by whomever) — first link wins
    session.add(
        Referral(referrer_telegram_id=referrer_tg, referred_telegram_id=referred_tg)
    )
    await session.flush()
    logger.info("REFERRAL: {} invited {}", referrer_tg, referred_tg)
    return True


async def reward_referrer_if_due(
    session: AsyncSession, paying_user: User
) -> int | None:
    """On a payment: reward the inviter once, return their tg id if rewarded."""
    if not settings.referral_enabled:
        return None
    result = await session.execute(
        select(Referral).where(
            Referral.referred_telegram_id == paying_user.telegram_id,
            Referral.rewarded.is_(False),
        )
    )
    referral = result.scalar_one_or_none()
    if referral is None:
        return None

    referrer = (
        await session.execute(
            select(User).where(User.telegram_id == referral.referrer_telegram_id)
        )
    ).scalar_one_or_none()
    if referrer is None:
        return None

    from app.database.models import PlanType
    from app.services.premium import activate_premium, record_payment

    sub = await activate_premium(
        session,
        referrer,
        days=settings.referral_reward_days,
        provider="referral",
        plan=PlanType.REFERRAL,
    )
    await record_payment(
        session, referrer, provider="referral", subscription_id=sub.id,
        status="granted",
        invoice_payload=f"referral:{settings.referral_reward_days}d",
    )
    referral.rewarded = True
    await session.flush()
    logger.info(
        "REFERRAL: rewarded {} with {}d for inviting {}",
        referrer.telegram_id, settings.referral_reward_days, paying_user.telegram_id,
    )
    return referrer.telegram_id
