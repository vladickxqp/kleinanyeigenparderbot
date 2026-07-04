"""Read-only rules listing for the admin panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import RuleOut
from app.api.security import require_admin
from app.database.models import SearchRule
from app.database.session import get_session

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=list[RuleOut])
async def list_rules(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[SearchRule]:
    result = await session.execute(
        select(SearchRule)
        .order_by(SearchRule.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
