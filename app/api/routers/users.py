"""Read-only user administration for the admin panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import UserOut
from app.api.security import require_admin
from app.database.models import SearchRule, User
from app.database.session import get_session

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[UserOut]:
    rules_count = (
        select(SearchRule.user_id, func.count(SearchRule.id).label("cnt"))
        .group_by(SearchRule.user_id)
        .subquery()
    )
    result = await session.execute(
        select(User, func.coalesce(rules_count.c.cnt, 0))
        .outerjoin(rules_count, rules_count.c.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    out: list[UserOut] = []
    for user, cnt in result.all():
        item = UserOut.model_validate(user)
        item.rules_count = int(cnt)
        out.append(item)
    return out
