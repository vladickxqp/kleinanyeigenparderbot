"""Deduplication of parsed listings.

Two levels of dedup:
  1. Within a single scrape run (same fingerprint returned twice).
  2. Against already-stored listings for the rule (persisted fingerprints).
"""

from __future__ import annotations

import hashlib
import re

from app.parsers.schemas import ParsedListing


def repost_key(site: object, title: str, price: float | None) -> str:
    """Soft identity of an OFFER, independent of which ad carries it.

    A seller who deletes an ad and posts it again gets a fresh ad id, so the
    hard fingerprint (site + id) sees a brand-new listing and the user is told
    about the same thing twice — or twenty times, which is how people push
    their ad back to the top of a Kleinanzeigen result list.

    Deliberately NOT identity: two sellers really can offer "PS5 Controller"
    at 25 EUR, which is why site+id decides what gets STORED. This only
    decides what gets DELIVERED a second time.

    Defined here rather than on the schema alone, so the stored row and the
    freshly parsed listing can never be keyed differently.
    """
    name = getattr(site, "value", site)
    normalised = re.sub(r"[^a-z0-9]+", "", (title or "").lower())
    bucket = int(price) if price is not None else -1
    raw = f"{name}|{normalised}|{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def dedup_within_batch(listings: list[ParsedListing]) -> list[ParsedListing]:
    """Drop duplicate fingerprints inside a single batch, keeping first seen."""
    seen: set[str] = set()
    unique: list[ParsedListing] = []
    for item in listings:
        fp = item.fingerprint
        if fp in seen:
            continue
        seen.add(fp)
        unique.append(item)
    return unique


def filter_new_listings(
    listings: list[ParsedListing], known_fingerprints: set[str]
) -> list[ParsedListing]:
    """Return only listings whose fingerprint is not already known.

    Combines batch-level and cross-run deduplication in one pass.
    """
    result: list[ParsedListing] = []
    seen = set(known_fingerprints)
    for item in dedup_within_batch(listings):
        fp = item.fingerprint
        if fp in seen:
            continue
        seen.add(fp)
        result.append(item)
    return result
