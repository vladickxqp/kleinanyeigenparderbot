"""Deduplication of parsed listings.

Two levels of dedup:
  1. Within a single scrape run (same fingerprint returned twice).
  2. Against already-stored listings for the rule (persisted fingerprints).
"""

from __future__ import annotations

from app.parsers.schemas import ParsedListing


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
