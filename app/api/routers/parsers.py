"""Expose the registered parsers to the admin panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas import ParserInfo
from app.api.security import require_admin
from app.parsers import registry

router = APIRouter(prefix="/parsers", tags=["parsers"])


@router.get("", response_model=list[ParserInfo])
async def list_parsers(_: dict = Depends(require_admin)) -> list[ParserInfo]:
    return [
        ParserInfo(
            site=p.site.value,
            label=p.label,
            requires_browser=p.requires_browser,
        )
        for p in registry
    ]
