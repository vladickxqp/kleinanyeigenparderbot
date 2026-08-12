"""Pydantic schemas that decouple parsers from the ORM.

A parser receives a :class:`SearchQuery` and returns :class:`ParsedListing`
objects. The service layer converts these into ORM ``Listing`` rows. This keeps
parsers pure and easily unit-testable.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

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
        """True if the query tokens appear in the texts (brand-tolerant).

        Marketplace search is fuzzy ("iPhone 17 Pro" also returns plain
        "iPhone 17" items), so all tokens must be present — EXCEPT that for
        queries with 3+ tokens the FIRST token (usually the brand) may be
        missing. Sellers often title listings "Model 3 Performance" without
        "Tesla"; those must still match a "tesla model 3" search. Trailing
        qualifiers stay mandatory: "iphone 17 pro" will not match a plain
        "iPhone 17", because "pro" is not the first token.

        Variants with EXTRA words always match: "Tesla Model 3 Long Range"
        contains every token of "tesla model 3".
        """
        haystack = " ".join(t.lower() for t in texts if t)
        tokens = [tok for tok in self.keywords.lower().split() if tok]
        if not tokens:
            return True
        missing = [tok for tok in tokens if tok not in haystack]
        if not missing:
            return True
        # Allow only the leading (brand) token to be absent on longer queries.
        return len(tokens) >= 3 and missing == [tokens[0]]


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
    #: When the ad was posted on the marketplace (None = unknown / promoted ad).
    posted_at: datetime | None = None
    #: Vehicle attributes (cars/motorbikes) — None for non-vehicle listings.
    mileage_km: int | None = None
    registration_year: int | None = None

    @property
    def is_vehicle(self) -> bool:
        """True if the listing carries vehicle attributes."""
        return self.mileage_km is not None or self.registration_year is not None

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
