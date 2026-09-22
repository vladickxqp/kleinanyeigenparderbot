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

from app.database.models.enums import Condition, SellerType, SiteName


class SearchQuery(BaseModel):
    """A normalised query derived from a user's SearchRule."""

    keywords: str
    exclude_keywords: list[str] = Field(default_factory=list)
    category: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    condition: Condition = Condition.ANY
    location: str | None = None
    zip_code: str | None = None
    max_distance_km: int | None = None
    exclude_auctions: bool = False
    #: None = shipping does not matter, True = only ads offering shipping,
    #: False = pickup only. Parsers that cannot tell must never filter on it.
    shipping_available: bool | None = None
    #: Vehicle bounds. Like shipping, these only ever judge an ad that STATES
    #: the value — see :meth:`matches_vehicle`.
    max_mileage_km: int | None = None
    min_year: int | None = None
    #: Who may be selling. Like every other filter here, it only judges an ad
    #: whose seller the marketplace actually names.
    seller_type: SellerType = SellerType.ANY
    max_results: int = 40

    def matches_seller(self, seller: "SellerType | None") -> bool:
        """Whether an ad survives the private/dealer filter.

        Unknown keeps the ad. Most marketplaces never say who is selling, and
        reading silence as "dealer" would empty a "private only" rule on every
        one of them at once.
        """
        if self.seller_type is SellerType.ANY or seller in (None, SellerType.ANY):
            return True
        return seller is self.seller_type

    @property
    def wants_vehicle_filter(self) -> bool:
        return self.max_mileage_km is not None or self.min_year is not None

    def matches_vehicle(
        self, mileage_km: int | None = None, registration_year: int | None = None
    ) -> bool:
        """Whether a car survives the mileage and registration bounds.

        Unknown keeps the ad, exactly as the shipping filter does. A marketplace
        that stops printing the kilometres on its cards would otherwise empty a
        paid rule overnight while every health check stayed green — and the
        user would simply stop getting deals with no way to tell why.
        """
        if self.max_mileage_km is not None and mileage_km is not None:
            if mileage_km > self.max_mileage_km:
                return False
        if self.min_year is not None and registration_year is not None:
            if registration_year < self.min_year:
                return False
        return True

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
    #: True/False when the marketplace says so, None when it cannot tell.
    #: Kept apart from ``shipping_cost`` so "we do not know" never reads as
    #: "no shipping" and silently empties a rule that filters on it.
    shipping_available: bool | None = None
    image_url: HttpUrl | None = None
    description: str | None = None
    location: str | None = None
    condition: Condition = Condition.ANY
    seller_name: str | None = None
    #: The marketplace's own id for the seller, where it has one. Preferred
    #: over the name for blocking: a dealer can rename itself, the id stays.
    seller_id: str | None = None
    seller_rating: float | None = None
    #: Private or dealer, when the marketplace says so. None means it does
    #: not — and a filter must read that as "unknown", never as "dealer".
    seller_type: SellerType | None = None
    is_auction: bool = False
    #: Asking price marked "VB" (Verhandlungsbasis) — negotiable.
    is_negotiable: bool = False
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
        """Identity hash: site + ad id.

        The ad id is what actually identifies an offer. Hashing only title and
        price made two different sellers collide whenever a common title met a
        common price ("PS5 Controller" at 25 €) — the second ad then counted as
        "already known" and was silently dropped, which is the worst possible
        outcome for a deal hunter. Reposts are still caught, by
        :attr:`repost_fingerprint`.
        """
        raw = f"{self.site.value}|{self.external_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @property
    def repost_fingerprint(self) -> str:
        """Soft hash: site + normalised title + rounded price.

        Same offer, new ad id — the classic Kleinanzeigen repost. Used as a
        secondary signal, never as identity.
        """
        # One definition, shared with the stored rows: keying them differently
        # would make repost suppression silently miss everything.
        from app.services.dedup import repost_key

        return repost_key(self.site, self.title, self.price)

    @property
    def total_price(self) -> float | None:
        if self.price is None:
            return None
        return self.price + (self.shipping_cost or 0.0)
