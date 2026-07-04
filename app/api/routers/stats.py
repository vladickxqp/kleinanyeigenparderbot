"""Dashboard statistics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DashboardStats
from app.api.security import require_admin
from app.database.models import Listing, SearchRule, User
from app.database.session import get_session
from app.parsers import registry

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> DashboardStats:
    users = await session.scalar(select(func.count(User.id))) or 0
    total_rules = await session.scalar(select(func.count(SearchRule.id))) or 0
    active_rules = (
        await session.scalar(
            select(func.count(SearchRule.id)).where(SearchRule.is_active.is_(True))
        )
        or 0
    )
    listings = await session.scalar(select(func.count(Listing.id))) or 0
    notified = (
        await session.scalar(
            select(func.count(Listing.id)).where(Listing.notified.is_(True))
        )
        or 0
    )
    return DashboardStats(
        users=users,
        active_rules=active_rules,
        total_rules=total_rules,
        listings=listings,
        notified=notified,
        parsers=len(registry),
    )
