"""Pydantic schemas that decouple parsers from the ORM.

A parser receives a :class:`SearchQuery` and returns :class:`ParsedListing`
objects. The service layer converts these into ORM ``Listing`` rows. This keeps
parsers pure and easily unit-testable.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.database.models.enums import Condition, SiteName


class SearchQuery(BaseModel):
    """A normalised query derived from a user's SearchRule."""

    keywords: str
    exclude_keywords: list[str] = Field(default_factory=list)
    category: str | None = None
    brand: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    condition: Condition = Condition.ANY
    location: str | None = None
    zip_code: str | None = None
    max_distance_km: int | None = None
    exclude_auctions: bool = False
    max_results: int = 40

    def matches_text(self, *texts: str | None) -> bool:
        """Return False if any exclude keyword appears in the given texts."""
        haystack = " ".join(t.lower() for t in texts if t)
        return not any(bad.lower() in haystack for bad in self.exclude_keywords)

    def contains_all_keywords(self, *texts: str | None) -> bool:
        """True if every whitespace-separated query token appears in the texts.

        Marketplace search is fuzzy ("iPhone 17 Pro" also returns plain
        "iPhone 17" items); this enforces that all tokens are present.
        """
        haystack = " ".join(t.lower() for t in texts if t)
        tokens = [tok for tok in self.keywords.lower().split() if tok]
        return all(tok in haystack for tok in tokens)


class ParsedListing(BaseModel):
    """A single offer as produced by a parser (pre-persistence)."""

    site: SiteName
    external_id: str
    title: str
    url: HttpUrl
    price: float | None = None
    original_price: float | None = None
    currency: str = "EUR"
    shipping_cost: float | None = None
    image_url: HttpUrl | None = None
    description: str | None = None
    location: str | None = None
    condition: Condition = Condition.ANY
    seller_name: str | None = None
    seller_rating: float | None = None
    is_auction: bool = False

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        return re.sub(r"\s+", " ", v).strip()

    @property
    def fingerprint(self) -> str:
        """Stable dedup hash: site + normalised title + rounded price.

        Rounded price makes minor re-listing price jitter still collide, while
        genuinely different offers get distinct fingerprints.
        """
        norm_title = re.sub(r"[^a-z0-9]+", "", self.title.lower())
        price_bucket = int(self.price) if self.price is not None else -1
        raw = f"{self.site.value}|{norm_title}|{price_bucket}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @property
    def total_price(self) -> float | None:
        if self.price is None:
            return None
        return self.price + (self.shipping_cost or 0.0)
