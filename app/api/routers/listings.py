"""Read-only listings feed for the admin panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ListingOut
from app.api.security import require_admin
from app.database.models import Listing
from app.database.session import get_session

router = APIRouter(prefix="/listings", tags=["listings"])


@router.get("", response_model=list[ListingOut])
async def list_listings(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    min_score: int = Query(default=0, ge=0, le=100),
    site: str | None = Query(default=None, description="Filter by marketplace"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Listing]:
    stmt = select(Listing).where(Listing.deal_score >= min_score)
    if site:
        stmt = stmt.where(Listing.site == site)
    stmt = stmt.order_by(Listing.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
