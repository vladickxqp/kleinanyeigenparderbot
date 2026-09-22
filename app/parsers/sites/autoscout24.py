"""Parser for autoscout24.de — Germany's largest car marketplace.

The result page is rendered from a Next.js payload embedded in the HTML
(``__NEXT_DATA__``), so no browser is needed and the values arrive already
structured: price, mileage and first registration as numbers instead of text
scraped out of a card. That also makes the parser far less fragile than a
CSS-selector one — a redesign moves markup around, not the JSON.

**AutoScout24 has no free-text search.** The ``q=`` parameter is accepted and
silently ignored: a request for "tesla model 3" and one for "zzzqqq" both
answer with the entire German inventory (~870.000 cars) and HTTP 200. A rule
is therefore only sent here once its keywords resolve to a make in
AutoScout24's *own* taxonomy, which this parser reads from the same payload
and caches. A rule for "iPhone 15" gets no request and no results at all,
because the alternative — sending it anyway — means answering a phone hunt
with every car in the country.

The taxonomy is read live rather than hard-coded: a list of 293 makes and
their model groups baked into the source would rot silently, and a make that
quietly disappeared would look exactly like a rule nobody wrote.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any
from urllib.parse import urlencode

from loguru import logger

from app.config.settings import settings
from app.database.models.enums import Condition, SellerType, SiteName
from app.parsers.base import BaseParser
from app.parsers.registry import register_parser
from app.parsers.schemas import ParsedListing, SearchQuery

BASE_URL = "https://www.autoscout24.de"
SEARCH_PATH = "/lst"

#: Results per result page — AutoScout24's own page size, not a choice of ours.
PAGE_SIZE = 20
#: Never walk more than this many pages for one rule, however large the cap.
MAX_PAGES = 5

#: How long the make list and a make's model groups stay cached. They change
#: a few times a year; refetching them per search would double our request
#: cost, and requests per minute is the resource the plans are sold by.
TAXONOMY_TTL_SECONDS = 12 * 3600

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

#: Colloquial names that are not AutoScout24's own label. Everything else is
#: matched against the live taxonomy, so this stays short on purpose.
MAKE_ALIASES: dict[str, str] = {
    "vw": "volkswagen",
    "mercedes": "mercedes benz",
    "benz": "mercedes benz",
    "alfa": "alfa romeo",
    "landrover": "land rover",
    "range": "land rover",
    "citroen": "citroen",
    "skoda": "skoda",
}

#: BMW is the one make whose model groups are numbered series ("3er"), while
#: people search for the engine variant ("320d"). Mapping the leading digit is
#: the difference between a rule that finds 3ers and one that walks the newest
#: 20 of 63.000 BMWs and matches nothing.
_SERIES_RE = re.compile(r"^(\d)\d{2}[a-z]*$")


# --- Text helpers ----------------------------------------------------------------
def fold(text: str) -> str:
    """Lowercase, strip diacritics, and reduce anything else to single spaces.

    "Citroën C3" and "citroen-c3" have to reach the same lookup key, otherwise
    a make matches or not depending on how the user typed it.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def tokens(text: str) -> list[str]:
    return fold(text).split()


def close_variant_spacing(text: str) -> str:
    """Write an engine variant the way a rule spells it: "320 d" -> "320d".

    Dealers type "BMW 320 d", people search for "320d". Comparing the two as
    they stand throws away exactly the cars the search asked for, and the site
    answers HTTP 200 the whole time, so nothing anywhere looks broken.
    Only a lone letter directly after a number is pulled in — words never run
    into each other.
    """
    return re.sub(r"(?<=\d)\s+(?=[a-z](?:\s|$))", "", text.lower())


def mentions(wanted: list[str], *texts: str | None) -> bool:
    """Whether every leftover keyword appears in the ad's text."""
    if not wanted:
        return True
    haystack = close_variant_spacing(" ".join(t for t in texts if t))
    return all(token in haystack for token in wanted)


def _int(value: Any) -> int | None:
    """First integer in ``value`` (handles "168.999 km" and 168999 alike)."""
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def _money(value: Any) -> float | None:
    """German money string to a number: "€ 23.750,-" -> 23750.0."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d,.]", "", str(value)).rstrip(",.")
    if not cleaned:
        return None
    # Thousands separator is a dot, decimals a comma — never the other way.
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _year(value: Any) -> int | None:
    """Registration year out of "12-2020", "12/2020" or "2020"."""
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


# --- Payload reading -------------------------------------------------------------
def extract_payload(html: str) -> dict[str, Any] | None:
    """The page's ``pageProps`` object, or None when the page is not one."""
    match = _NEXT_DATA_RE.search(html)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError as exc:
        logger.debug("[autoscout24] payload is not valid JSON: {}", exc)
        return None
    props = data.get("props")
    if not isinstance(props, dict):
        return None
    page_props = props.get("pageProps")
    return page_props if isinstance(page_props, dict) else None


def read_makes(page_props: dict[str, Any]) -> dict[str, int]:
    """Folded make label -> AutoScout24 make id, from the page's own taxonomy."""
    taxonomy = page_props.get("taxonomy") or {}
    makes: dict[str, int] = {}
    for entry in taxonomy.get("makesSorted") or []:
        label, value = entry.get("label"), entry.get("value")
        if isinstance(label, str) and isinstance(value, int):
            makes[fold(label)] = value
    return makes


def read_model_groups(page_props: dict[str, Any], make_id: int) -> dict[str, int]:
    """Folded model-group label -> group id, for one make."""
    taxonomy = page_props.get("taxonomy") or {}
    raw = (taxonomy.get("modelGroups") or {}).get(str(make_id)) or []
    groups: dict[str, int] = {}
    for entry in raw:
        label, value = entry.get("label"), entry.get("value")
        if isinstance(label, str) and value is not None:
            groups[fold(label)] = int(value)
    return groups


# --- Query resolution ------------------------------------------------------------
def resolve_make(keywords: str, makes: dict[str, int]) -> tuple[int, list[str]] | None:
    """Make id and the tokens left over, or None when this is not a car search.

    Only a make at the START of the keywords counts. Scanning the whole string
    would let two-letter makes such as "AC" match inside "PS5 AC Adapter" and
    send a console hunt to a car marketplace; and people write the brand first
    anyway ("BMW 320d", "VW Golf"), which is the same assumption
    :meth:`SearchQuery.contains_all_keywords` already makes.
    """
    words = tokens(keywords)
    if not words:
        return None
    for size in range(min(3, len(words)), 0, -1):
        window = " ".join(words[:size])
        make_id = makes.get(window)
        if make_id is None:
            alias = MAKE_ALIASES.get(window)
            make_id = makes.get(alias) if alias else None
        if make_id is not None:
            return make_id, words[size:]
    return None


def resolve_model_group(
    rest: list[str], groups: dict[str, int]
) -> tuple[int | None, list[str]]:
    """Model-group id for the tokens after the make, plus the tokens left over.

    What the group name consumed is not checked against the ad text again: the
    search already asked AutoScout24 for that group, so every answer is one.
    Re-checking it would drop every 3er whose title reads "BMW 320 d" rather
    than "3er" — which is nearly all of them.
    """
    if not rest or not groups:
        return None, rest
    for size in range(min(3, len(rest)), 0, -1):
        group_id = groups.get(" ".join(rest[:size]))
        if group_id is not None:
            return group_id, rest[size:]

    # "320d" means the 3er. Only applied when the make actually numbers its
    # groups that way, so it cannot invent a series for anybody else — and the
    # token stays in the leftovers, because "320d" says more than "3er" does.
    match = _SERIES_RE.match(rest[0])
    if match is not None:
        series = groups.get(f"{match.group(1)}er")
        if series is not None:
            return series, rest
    return None, rest


def build_search_url(
    query: SearchQuery, *, make_id: int, group_id: int | None, page: int = 1
) -> str:
    """The result-page URL for one make/model and the rule's own filters."""
    category = f"ma{make_id}" + (f"gr{group_id}" if group_id is not None else "")
    params: dict[str, str | int] = {
        "atype": "C",          # cars, not motorbikes or trailers
        "cy": "D",             # Germany
        "cat": category,
        # "age" is AutoScout24's own "Neueste Angebote zuerst" — the only order
        # a deal hunter can use, since a car listed weeks ago is already picked
        # over. desc=0 is what the site itself generates for it.
        "sort": "age",
        "desc": 0,
    }
    if query.min_price is not None:
        params["pricefrom"] = int(query.min_price)
    if query.max_price is not None:
        params["priceto"] = int(query.max_price)
    if query.zip_code and query.max_distance_km:
        params["zip"] = query.zip_code
        params["zipr"] = int(query.max_distance_km)
    # Asked server-side so the 20 cards per page are 20 usable ones; the local
    # check still runs, because a parameter the site quietly drops would
    # otherwise pass unfiltered results straight through.
    if query.max_mileage_km is not None:
        params["kmto"] = int(query.max_mileage_km)
    if query.min_year is not None:
        params["fregfrom"] = int(query.min_year)
    # Verified live: custtype=P really does return private sellers only.
    if query.seller_type is SellerType.PRIVATE:
        params["custtype"] = "P"
    elif query.seller_type is SellerType.DEALER:
        params["custtype"] = "D"
    # The damage filter is applied server-side where possible, but never relied
    # on: the flag is missing on some cards, and an unknown value must not
    # decide anything on its own (see _listing_condition).
    params["damaged_listing"] = (
        "only" if query.condition is Condition.DEFECTIVE else "exclude"
    )
    if page > 1:
        params["page"] = page
    return f"{BASE_URL}{SEARCH_PATH}?{urlencode(params)}"


# --- Listing parsing -------------------------------------------------------------
def _title(vehicle: dict[str, Any]) -> str:
    """Readable title from make, model and the seller's version line."""
    make = (vehicle.get("make") or "").strip()
    model = (vehicle.get("model") or vehicle.get("modelGroup") or "").strip()
    # Sellers type the version as "MODEL 3 LONG RANGE AWD | AIR LIFT SYSTEM |".
    version = re.sub(r"\s*\|\s*", " ", vehicle.get("modelVersionInput") or "")
    version = re.sub(r"\s+", " ", version).strip()

    if version and model and model.lower() in version.lower():
        # The version already repeats the model — printing both reads as
        # "Tesla Model 3 MODEL 3 LONG RANGE".
        return f"{make} {version}".strip()
    return " ".join(part for part in (make, model, version) if part).strip()


def _listing_condition(vehicle: dict[str, Any]) -> Condition:
    """What the structured fields say about the car's state.

    ``isCurrentlyDamaged`` is absent on some cards. Absent means unknown, and
    unknown is not damage — the offer type still tells us whether the car was
    ever registered.
    """
    if vehicle.get("isCurrentlyDamaged") is True:
        return Condition.DEFECTIVE
    # N = Neuwagen. Everything else (U, D, J, O, A) has been registered and
    # driven, whatever the letter stands for.
    if (vehicle.get("offerType") or "").upper() == "N":
        return Condition.NEW
    return Condition.USED


def condition_matches(wanted: Condition, offered: Condition) -> bool:
    """Whether a car survives the rule's condition filter."""
    if wanted in (Condition.ANY, Condition.LIKE_NEW, Condition.REFURBISHED):
        return True
    if wanted is Condition.USED:
        # "Gebraucht" means "not broken", exactly as on Kleinanzeigen.
        return offered is not Condition.DEFECTIVE
    return offered is wanted


def _seller_type(seller: dict[str, Any]) -> SellerType | None:
    """Map AutoScout24's own wording; anything else stays unknown.

    A value this parser does not recognise must not become "dealer" — a
    renamed type would otherwise quietly empty every "private only" rule.
    """
    raw = str(seller.get("type") or "").strip().lower()
    if raw in {"privateseller", "private"}:
        return SellerType.PRIVATE
    if raw == "dealer":
        return SellerType.DEALER
    return None


def parse_listing(raw: dict[str, Any]) -> ParsedListing | None:
    """One entry of the payload's ``listings`` array, or None if unusable."""
    listing_id = raw.get("id")
    path = raw.get("url")
    if not isinstance(listing_id, str) or not isinstance(path, str) or not path:
        return None

    vehicle = raw.get("vehicle") or {}
    title = _title(vehicle)
    if not title:
        return None

    price_block = raw.get("price") or {}
    tracking = raw.get("tracking") or {}
    location = raw.get("location") or {}
    seller = raw.get("seller") or {}

    price = _money(price_block.get("priceRaw"))
    # AutoScout24 marks reduced offers with the previous asking price; it is
    # only worth carrying when it really is higher than what is asked now.
    previous = _money(
        (raw.get("superDeal") or {}).get("oldPriceFormatted")
        or price_block.get("oldSuperDealPrice")
    )
    if previous is not None and price is not None and previous <= price:
        previous = None

    images = [img for img in (raw.get("images") or []) if isinstance(img, str)]
    place = " ".join(
        str(part) for part in (location.get("zip"), location.get("city")) if part
    ).strip()

    return ParsedListing(
        site=SiteName.AUTOSCOUT24,
        external_id=listing_id,
        title=title,
        url=f"{BASE_URL}{path}" if path.startswith("/") else path,
        price=price,
        original_price=previous,
        currency="EUR",
        image_url=images[0] if images else None,
        description=(vehicle.get("subtitle") or None),
        location=place or None,
        condition=_listing_condition(vehicle),
        seller_name=(seller.get("companyName") or None),
        seller_id=(str(seller["id"]) if seller.get("id") else None),
        seller_type=_seller_type(seller),
        # Cars are collected, never shipped, and AutoScout24 runs no auctions:
        # filtering on either would empty every rule that sets it.
        shipping_available=None,
        is_auction=False,
        mileage_km=_int(tracking.get("mileage") or vehicle.get("mileageInKm")),
        registration_year=_year(tracking.get("firstRegistration")),
        # AutoScout24 does not publish when an ad went online. None means
        # unknown here, and the pipeline already treats it that way.
        posted_at=None,
    )


def parse_listings(page_props: dict[str, Any]) -> list[ParsedListing]:
    """Every usable offer on one result page."""
    results: list[ParsedListing] = []
    for raw in page_props.get("listings") or []:
        if not isinstance(raw, dict):
            continue
        try:
            parsed = parse_listing(raw)
        except Exception as exc:  # noqa: BLE001 - one bad card is not a failure
            logger.debug("[autoscout24] skipped card: {}", exc)
            continue
        if parsed is not None:
            results.append(parsed)
    return results


class AutoScout24Parser(BaseParser):
    """Extracts car offers from autoscout24.de result pages."""

    site = SiteName.AUTOSCOUT24
    label = "AutoScout24"
    requires_browser = False

    def __init__(self) -> None:
        super().__init__()
        self._makes: dict[str, int] = {}
        self._makes_at: float = 0.0
        self._groups: dict[int, tuple[float, dict[str, int]]] = {}

    # --- Taxonomy (cached) -----------------------------------------------------
    def _fresh(self, stamp: float) -> bool:
        return bool(stamp) and (time.monotonic() - stamp) < TAXONOMY_TTL_SECONDS

    async def _load_makes(self) -> dict[str, int]:
        if self._fresh(self._makes_at) and self._makes:
            return self._makes
        html = await self.fetch_text(f"{BASE_URL}{SEARCH_PATH}?atype=C&cy=D")
        page_props = extract_payload(html)
        if page_props is None:
            # No payload at all is not "no cars" — it is a page we did not get.
            self.mark_suspected_block()
            return {}
        makes = read_makes(page_props)
        if makes:
            self._makes, self._makes_at = makes, time.monotonic()
        return makes

    async def _load_groups(self, make_id: int) -> dict[str, int]:
        cached = self._groups.get(make_id)
        if cached and self._fresh(cached[0]):
            return cached[1]
        html = await self.fetch_text(
            f"{BASE_URL}{SEARCH_PATH}?{urlencode({'atype': 'C', 'cy': 'D', 'cat': f'ma{make_id}'})}"
        )
        page_props = extract_payload(html)
        if page_props is None:
            self.mark_suspected_block()
            return {}
        groups = read_model_groups(page_props, make_id)
        self._groups[make_id] = (time.monotonic(), groups)
        return groups

    # --- Search ----------------------------------------------------------------
    async def search(self, query: SearchQuery) -> list[ParsedListing]:
        makes = await self._load_makes()
        if not makes:
            return []

        resolved = resolve_make(query.keywords, makes)
        if resolved is None:
            # Not a car search. Saying so costs one log line; sending it anyway
            # would answer with the whole German inventory.
            logger.debug(
                "[autoscout24] {!r} names no known make — skipping", query.keywords
            )
            return []
        make_id, rest = resolved
        group_id, leftover = resolve_model_group(
            rest, await self._load_groups(make_id)
        )

        results: list[ParsedListing] = []
        pages = min(MAX_PAGES, max(1, -(-query.max_results // PAGE_SIZE)))
        for page in range(1, pages + 1):
            url = build_search_url(query, make_id=make_id, group_id=group_id, page=page)
            logger.debug("[autoscout24] GET {}", url)
            page_props = extract_payload(await self.fetch_text(url))
            if page_props is None:
                self.mark_suspected_block()
                break
            if "listings" not in page_props:
                # The key is always there on a result page, even when it is
                # empty — its absence means we were served something else.
                self.mark_suspected_block()
                break

            batch = parse_listings(page_props)
            for item in batch:
                if not self._wanted(item, query, leftover):
                    continue
                results.append(item)
                if len(results) >= query.max_results:
                    return results
            if len(batch) < PAGE_SIZE:
                break  # last page
        return results

    @staticmethod
    def _wanted(
        item: ParsedListing, query: SearchQuery, leftover: list[str]
    ) -> bool:
        """Local filters for what the URL could not express.

        Only the keywords the taxonomy did NOT consume are checked against the
        text — make and model were already filtered server-side, and asking the
        ad to repeat them in its title is how a working search returns nothing.
        """
        if not query.matches_text(item.title, item.description):
            return False
        if not mentions(leftover, item.title, item.description):
            return False
        if not condition_matches(query.condition, item.condition):
            return False
        if not query.matches_seller(item.seller_type):
            return False
        if not query.matches_vehicle(item.mileage_km, item.registration_year):
            return False
        if query.max_price is not None and item.price is not None:
            if item.price > query.max_price:
                return False
        if query.min_price is not None and item.price is not None:
            if item.price < query.min_price:
                return False
        return True


# Registered at the end rather than by decorator, so the site has an off switch:
# a rule with no sites chosen resolves to EVERY registered parser, which is how
# a new marketplace reaches all existing users on the next deploy.
if settings.autoscout24_enabled:
    register_parser(AutoScout24Parser)
