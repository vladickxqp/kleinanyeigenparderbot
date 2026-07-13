"""Coupon engine: creation, validation, redemption and price calculation.

Benefit types (exactly one per coupon):
- ``discount_percent``     — % off the Stars price of the next purchase
- ``discount_fixed_stars`` — fixed Stars off the next purchase
- ``free_days``            — instant free premium days (no purchase needed)

Discount coupons are attached to the invoice payload
(``premium_monthly:CODE``) and only counted as used once the purchase actually
succeeds. Free-days coupons are counted at redemption time.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Coupon, CouponRedemption


class CouponError(Exception):
    """Raised with a user-presentable German message."""


async def get_coupon(session: AsyncSession, code: str) -> Coupon | None:
    result = await session.execute(
        select(Coupon).where(Coupon.code == code.strip().upper())
    )
    return result.scalar_one_or_none()


async def validate_coupon(
    session: AsyncSession, code: str, telegram_id: int
) -> Coupon:
    """Return the coupon if the user may redeem it, else raise CouponError."""
    coupon = await get_coupon(session, code)
    if coupon is None or not coupon.is_active:
        raise CouponError("Diesen Code gibt es nicht (oder er ist deaktiviert).")
    if coupon.valid_until is not None:
        now = datetime.now(timezone.utc)
        valid_until = coupon.valid_until
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        if valid_until < now:
            raise CouponError("Dieser Code ist abgelaufen.")
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        raise CouponError("Dieser Code wurde bereits zu oft eingelöst.")
    already = await session.execute(
        select(CouponRedemption).where(
            CouponRedemption.coupon_id == coupon.id,
            CouponRedemption.telegram_id == telegram_id,
        )
    )
    if already.scalar_one_or_none() is not None:
        raise CouponError("Du hast diesen Code schon benutzt.")
    return coupon


def discounted_price_stars(coupon: Coupon) -> int:
    """Stars price of one premium month after applying a discount coupon."""
    price = settings.premium_price_stars
    if coupon.discount_percent:
        price = round(price * (100 - coupon.discount_percent) / 100)
    elif coupon.discount_fixed_stars:
        price = price - coupon.discount_fixed_stars
    return max(1, int(price))  # Telegram requires a positive amount


async def mark_redeemed(
    session: AsyncSession, coupon: Coupon, telegram_id: int
) -> None:
    """Book a redemption (called at grant time or successful purchase)."""
    coupon.used_count += 1
    session.add(CouponRedemption(coupon_id=coupon.id, telegram_id=telegram_id))
    await session.flush()
    logger.info(
        "COUPON: {} redeemed by {} ({}/{})",
        coupon.code, telegram_id, coupon.used_count, coupon.max_uses or "∞",
    )


async def create_coupon(
    session: AsyncSession,
    *,
    code: str,
    created_by: int,
    discount_percent: int | None = None,
    discount_fixed_stars: int | None = None,
    free_days: int | None = None,
    max_uses: int | None = None,
    valid_until: datetime | None = None,
) -> Coupon:
    """Create a coupon; exactly one benefit must be given."""
    benefits = [discount_percent, discount_fixed_stars, free_days]
    if sum(1 for b in benefits if b) != 1:
        raise CouponError(
            "Genau EIN Vorteil nötig: percent=, stars= ODER days=."
        )
    if discount_percent is not None and not (1 <= discount_percent <= 100):
        raise CouponError("percent muss zwischen 1 und 100 liegen.")
    code = code.strip().upper()
    if await get_coupon(session, code) is not None:
        raise CouponError(f"Code {code} existiert bereits.")
    coupon = Coupon(
        code=code,
        created_by=created_by,
        discount_percent=discount_percent,
        discount_fixed_stars=discount_fixed_stars,
        free_days=free_days,
        max_uses=max_uses,
        valid_until=valid_until,
    )
    session.add(coupon)
    await session.flush()
    logger.info("COUPON: {} created by {}", code, created_by)
    return coupon
