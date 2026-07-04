"""Pydantic response/request models for the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str
    parsers: int


class ParserInfo(BaseModel):
    site: str
    label: str
    requires_browser: bool


class DashboardStats(BaseModel):
    users: int
    active_rules: int
    total_rules: int
    listings: int
    notified: int
    parsers: int


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    keywords: str
    max_price: float | None
    is_active: bool
    interval_seconds: int
    min_deal_score: int
    created_at: datetime


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site: str
    title: str
    url: str
    price: float | None
    deal_score: int
    deal_verdict: str
    location: str | None
    created_at: datetime
