"""Flip tracking: purchases, sales, realised profit and the flip-only mode.

Money math (single source of truth, configurable via RESALE_FEE_PERCENT and
RESALE_SHIPPING_EUR):

    proceeds   = sale_price × (1 − fee%)
    fees_eur   = sale_price − proceeds + shipping
    net_profit = sale_price − fees_eur − buy_price

The flip-only mode is a per-user threshold in Redis: rules then only deliver
listings whose ESTIMATED net profit (against the market price) reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Flip, FlipStatus, Listing


# --- Money math ----------------------------------------------------------------------
def fees_for_sale(sale_price: float) -> float:
    """Marketplace fee share plus flat shipping for a sale at ``sale_price``."""
    fee_share = sale_price * settings.resale_fee_percent / 100
    return round(fee_share + settings.resale_shipping_eur, 2)


def net_profit(buy_price: float, sale_price: float) -> float:
    """Realised profit of a completed flip after fees and shipping."""
    return round(sale_price - fees_for_sale(sale_price) - buy_price, 2)


def estimated_net_profit(price: float, market: float) -> float:
    """Expected profit if bought at ``price`` and resold at ``market``."""
    return net_profit(price, market)


def passes_flip_mode(
    price: float | None, market: float | None, min_net: float | None
) -> bool:
    """Flip-only gate: True if the listing may be delivered.

    No threshold → everything passes. Unknown market price → passes too (a
    young rule has no history yet; hiding everything would be worse than
    showing an unrated listing).
    """
    if not min_net:
        return True
    if price is None or market is None:
        return True
    return estimated_net_profit(price, market) >= min_net


# --- Purchases & sales ----------------------------------------------------------------
async def record_purchase(
    session: AsyncSession, telegram_id: int, listing: Listing, buy_price: float
) -> Flip:
    flip = Flip(
        telegram_id=telegram_id,
        listing_id=listing.id,
        title=listing.title[:512],
        source_url=listing.url[:1024] if listing.url else None,
        buy_price=round(buy_price, 2),
        status=FlipStatus.BOUGHT,
    )
    session.add(flip)
    await session.flush()
    logger.info("FLIP: {} bought '{}' for {}", telegram_id, listing.title[:40], buy_price)
    return flip


async def record_sale(session: AsyncSession, flip: Flip, sale_price: float) -> Flip:
    flip.sell_price = round(sale_price, 2)
    flip.fees_eur = fees_for_sale(sale_price)
    flip.net_profit = net_profit(flip.buy_price, sale_price)
    flip.status = FlipStatus.SOLD
    flip.sold_at = datetime.now(timezone.utc)
    await session.flush()
    logger.info(
        "FLIP: {} sold '{}' {} -> {} (net {})",
        flip.telegram_id, flip.title[:40], flip.buy_price, sale_price, flip.net_profit,
    )
    return flip


async def cancel_flip(session: AsyncSession, flip: Flip) -> None:
    flip.status = FlipStatus.CANCELED
    await session.flush()


async def get_flip(session: AsyncSession, flip_id: int, telegram_id: int) -> Flip | None:
    """A flip by id, scoped to its owner (never trust callback data alone)."""
    flip = await session.get(Flip, flip_id)
    if flip is None or flip.telegram_id != telegram_id:
        return None
    return flip


async def open_flips(session: AsyncSession, telegram_id: int) -> list[Flip]:
    result = await session.execute(
        select(Flip)
        .where(Flip.telegram_id == telegram_id, Flip.status == FlipStatus.BOUGHT)
        .order_by(Flip.bought_at.desc())
        .limit(30)
    )
    return list(result.scalars().all())


# --- Statistics -------------------------------------------------------------------------
@dataclass(slots=True)
class FlipStats:
    open_count: int
    invested_open: float
    sold_count: int
    revenue: float
    fees: float
    net_profit: float
    net_last_30d: float
    best_title: str | None
    best_net: float | None

    @property
    def avg_margin_pct(self) -> float | None:
        """Average net margin on sold flips relative to purchase cost."""
        if self.sold_count == 0 or self.revenue <= 0:
            return None
        cost = self.revenue - self.fees - self.net_profit
        return round(self.net_profit / cost * 100, 1) if cost > 0 else None


async def profit_stats(session: AsyncSession, telegram_id: int) -> FlipStats:
    open_count, invested = (
        await session.execute(
            select(func.count(Flip.id), func.coalesce(func.sum(Flip.buy_price), 0.0))
            .where(Flip.telegram_id == telegram_id, Flip.status == FlipStatus.BOUGHT)
        )
    ).one()
    sold_count, revenue, fees, net = (
        await session.execute(
            select(
                func.count(Flip.id),
                func.coalesce(func.sum(Flip.sell_price), 0.0),
                func.coalesce(func.sum(Flip.fees_eur), 0.0),
                func.coalesce(func.sum(Flip.net_profit), 0.0),
            ).where(Flip.telegram_id == telegram_id, Flip.status == FlipStatus.SOLD)
        )
    ).one()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    net_30 = await session.scalar(
        select(func.coalesce(func.sum(Flip.net_profit), 0.0)).where(
            Flip.telegram_id == telegram_id,
            Flip.status == FlipStatus.SOLD,
            Flip.sold_at >= cutoff,
        )
    )
    best = (
        await session.execute(
            select(Flip)
            .where(Flip.telegram_id == telegram_id, Flip.status == FlipStatus.SOLD)
            .order_by(Flip.net_profit.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return FlipStats(
        open_count=int(open_count or 0),
        invested_open=float(invested or 0.0),
        sold_count=int(sold_count or 0),
        revenue=float(revenue or 0.0),
        fees=float(fees or 0.0),
        net_profit=float(net or 0.0),
        net_last_30d=float(net_30 or 0.0),
        best_title=best.title if best else None,
        best_net=best.net_profit if best else None,
    )


# --- Flip-only mode (per-user threshold in Redis) ----------------------------------------
async def set_flip_min(telegram_id: int, min_net: float | None) -> None:
    try:
        from app.services.health import _redis

        async with _redis() as r:
            key = f"flipmode:{telegram_id}"
            if min_net:
                await r.set(key, str(float(min_net)))
            else:
                await r.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("flips.set_flip_min failed: {}", exc)


async def get_flip_min(telegram_id: int) -> float | None:
    try:
        from app.services.health import _redis

        async with _redis() as r:
            raw = await r.get(f"flipmode:{telegram_id}")
        return float(raw) if raw else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("flips.get_flip_min failed: {}", exc)
        return None
