"""Relevance filtering: keep search results on-topic.

Marketplace keyword search is fuzzy — searching "iPhone 17 Pro" also returns
cases ("Hülle für iPhone 17 Pro"), chargers, screen protectors and wanted-ads.
This module removes such noise BEFORE price statistics are computed, so cheap
accessories no longer look like incredible deals next to the real product.
"""

from __future__ import annotations

import re

from loguru import logger

from app.database.models.enums import Condition
from app.parsers.schemas import ParsedListing, SearchQuery

#: Accessory / noise words filtered out by default. A word is only applied if it
#: does NOT appear in the user's own keywords (searching "iphone hülle" must
#: obviously still return cases).
ACCESSORY_WORDS: tuple[str, ...] = (
    "hülle", "hüllen", "case", "cover", "schutzhülle", "tasche",
    "panzerglas", "schutzglas", "schutzfolie", "displayschutz", "folie",
    "ladekabel", "kabel", "ladegerät", "ladegeraet", "netzteil", "adapter",
    "halterung", "ständer", "staender", "dockingstation",
    "dummy", "attrappe", "ersatzteil", "ersatzdisplay", "ersatzakku",
    "reparatur", "platine",
)

#: Titles starting with these are wanted-ads ("Suche iPhone..."), not offers.
_WANTED_AD_PREFIXES: tuple[str, ...] = ("suche ", "gesuch", "kaufe ", "ich suche")

#: Noise for a normal search, but the actual target of a defect hunt: broken
#: units, boards and spare-part lots are where a repairer makes their margin.
_REPAIR_WORDS: frozenset[str] = frozenset(
    {"reparatur", "ersatzteil", "ersatzdisplay", "ersatzakku", "platine"}
)


def _active_accessory_words(query: SearchQuery) -> list[str]:
    """Accessory words that are safe to filter for this query."""
    kw = query.keywords.lower()
    words = [w for w in ACCESSORY_WORDS if w not in kw]
    if query.condition is Condition.DEFECTIVE:
        # This pass runs before anything else sees the batch — leaving the
        # repair words in would throw away exactly the ads the rule asks for.
        words = [w for w in words if w not in _REPAIR_WORDS]
    return words


def is_relevant(query: SearchQuery, item: ParsedListing) -> bool:
    """Decide whether a parsed listing genuinely matches the query intent."""
    title = item.title.lower()
    text = f"{title} {(item.description or '').lower()}"

    # 1) Wanted-ads are never deals.
    if any(title.startswith(p) for p in _WANTED_AD_PREFIXES):
        return False

    # 2) Every query token must appear somewhere in title+description.
    if not query.contains_all_keywords(item.title, item.description):
        return False

    # 3) Accessory noise: filter titles dominated by accessory words, unless
    #    the user explicitly searches for accessories.
    for word in _active_accessory_words(query):
        # Both boundaries matter: without the right one "kabel" also matches
        # inside "kabellose", and every wireless mouse was thrown away as a
        # cable accessory. German compounds are still caught because the
        # accessory word then ends the token ("ladekabel", "handyhuelle").
        if re.search(rf"(?<![a-zäöüß]){re.escape(word)}(?![a-zäöüß])", title):
            return False

    # 4) User-defined exclude words (also enforced in parsers; kept here so the
    #    guarantee holds for every parser implementation).
    return query.matches_text(item.title, item.description)


def filter_relevant(
    query: SearchQuery, listings: list[ParsedListing]
) -> list[ParsedListing]:
    """Return only listings that pass :func:`is_relevant`, with debug logging."""
    kept: list[ParsedListing] = []
    dropped = 0
    for item in listings:
        if is_relevant(query, item):
            kept.append(item)
        else:
            dropped += 1
    if dropped:
        logger.debug(
            "Relevance filter dropped {}/{} listing(s) for {!r}",
            dropped, len(listings), query.keywords,
        )
    return kept
