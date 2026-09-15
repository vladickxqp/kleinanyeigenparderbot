"""Telegram Mini App API — the user's own data, authenticated via initData.

Every endpoint is scoped to the calling Telegram user; there is no way to
address another user's rules, flips or payments.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.webapp_auth import current_webapp_user
from app.config.settings import settings
from app.database.models import Listing, SearchRule, User
from app.database.session import get_session
from app.services import flips as flip_svc
from app.services import premium
from app.services.repositories import SearchRuleRepository
from app.services.roles import effective_role

router = APIRouter(prefix="/webapp", tags=["webapp"])


# --- Schemas ----------------------------------------------------------------------
class MeOut(BaseModel):
    telegram_id: int
    name: str
    role: str
    tier: str
    is_paid: bool
    premium_until: datetime | None
    renews: bool
    last_charge_at: datetime | None
    next_charge_at: datetime | None
    flip_min_net: float | None
    price_stars: int
    price_eur: float


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    keywords: str
    is_active: bool
    interval_seconds: int
    min_price: float | None
    max_price: float | None
    location: str | None
    max_distance_km: int | None
    category: str | None


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site: str
    title: str
    url: str
    image_url: str | None
    price: float | None
    estimated_market_price: float | None
    deal_score: int
    deal_verdict: str
    location: str | None
    is_favorite: bool
    created_at: datetime


class FlipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    buy_price: float
    sell_price: float | None
    net_profit: float | None
    status: str
    bought_at: datetime
    sold_at: datetime | None


class FlipStatsOut(BaseModel):
    open_count: int
    invested_open: float
    sold_count: int
    revenue: float
    fees: float
    net_profit: float
    net_last_30d: float
    avg_margin_pct: float | None
    best_title: str | None
    best_net: float | None


class FlipsOut(BaseModel):
    stats: FlipStatsOut
    open: list[FlipOut]


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    amount_stars: int
    amount_eur: float
    status: str
    refunded: bool
    is_renewal: bool
    coupon_code: str | None
    created_at: datetime


# --- Endpoints ----------------------------------------------------------------------
@router.get("/me", response_model=MeOut)
async def me(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    billing = await premium.billing_info(session, user.telegram_id)
    renews = bool(
        sub
        and sub.payment_provider == "telegram_stars"
        and sub.payment_status != premium.CANCEL_AT_PERIOD_END
    )
    return MeOut(
        telegram_id=user.telegram_id,
        name=user.display_name,
        role=effective_role(user).value,
        tier=user.subscription.value,
        is_paid=user.is_paid_tier,
        premium_until=sub.subscription_end if sub else None,
        renews=renews,
        last_charge_at=billing.last_charge_at,
        next_charge_at=billing.next_charge_at if renews else None,
        flip_min_net=await flip_svc.get_flip_min(user.telegram_id),
        price_stars=settings.premium_price_stars,
        price_eur=settings.premium_price_eur,
    )


@router.get("/rules", response_model=list[RuleOut])
async def rules(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> list[SearchRule]:
    return list(await SearchRuleRepository(session).list_for_user(user.id))


@router.post("/rules/{rule_id}/toggle", response_model=RuleOut)
async def toggle_rule(
    rule_id: int,
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> SearchRule:
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Suche nicht gefunden")
    rule.is_active = not rule.is_active
    await session.commit()
    await session.refresh(rule)
    return rule


@router.get("/listings", response_model=list[ListingOut])
async def listings(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=30, le=100),
    favorites: bool = Query(default=False),
) -> list[Listing]:
    stmt = (
        select(Listing)
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .where(SearchRule.user_id == user.id, Listing.is_ignored.is_(False))
    )
    if favorites:
        stmt = stmt.where(Listing.is_favorite.is_(True))
    else:
        stmt = stmt.where(Listing.notified.is_(True))
    result = await session.execute(
        stmt.order_by(Listing.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/flips", response_model=FlipsOut)
async def flips(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> FlipsOut:
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    open_items = await flip_svc.open_flips(session, user.telegram_id)
    return FlipsOut(
        stats=FlipStatsOut(
            open_count=stats.open_count,
            invested_open=stats.invested_open,
            sold_count=stats.sold_count,
            revenue=stats.revenue,
            fees=stats.fees,
            net_profit=stats.net_profit,
            net_last_30d=stats.net_last_30d,
            avg_margin_pct=stats.avg_margin_pct,
            best_title=stats.best_title,
            best_net=stats.best_net,
        ),
        open=[FlipOut.model_validate(f) for f in open_items],
    )


@router.get("/payments", response_model=list[PaymentOut])
async def payments(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
):
    return await premium.payment_history(session, user.telegram_id)
