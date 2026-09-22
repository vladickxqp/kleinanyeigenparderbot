"""Parser for kleinanzeigen.de (formerly eBay Kleinanzeigen).

This is the reference implementation. It builds an SEO search URL, fetches the
result page with the polite base-class HTTP client and extracts listings from the
``article.aditem`` cards. HTML structure on classifieds sites changes over time —
the selectors below are defensive and degrade gracefully (a missing field yields
``None`` rather than an exception).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup, Tag
from loguru import logger

from app.config.clock import local_now
from app.database.models.enums import Condition, SiteName
from app.parsers.base import BaseParser
from app.parsers.registry import register_parser
from app.parsers.schemas import ParsedListing, SearchQuery

BASE_URL = "https://www.kleinanzeigen.de"

#: Category slug (as stored on SearchRule.category) -> Kleinanzeigen c-id.
#: The final URL suffix is ``k0c<id>``; verify ids against the live site when
#: adding new ones (wrong ids silently return other categories).
CATEGORY_IDS: dict[str, str] = {
    "handys": "173",          # Handy & Telefon
    "notebooks": "278",       # Notebooks
    "pcs": "228",             # PCs
    "pc-zubehoer": "225",     # PC-Zubehör & Software (Grafikkarten etc.)
    "konsolen": "279",        # Konsolen
    "elektronik": "161",      # Elektronik (Oberkategorie)
    "autos": "216",           # Autos
    "fahrraeder": "217",      # Fahrräder & Zubehör
}

# --- Condition heuristic ------------------------------------------------------
# Kleinanzeigen result cards carry no condition field, and the detail page would
# cost one extra request per ad. The condition filter is therefore a text
# heuristic over title + description, with the same word boundaries the
# relevance filter uses.

#: "neu" is listed WITHOUT its inflected forms on purpose: "neuer Akku" and
#: "neue Schutzfolie" appear in a large share of used-phone ads and would flip
#: every one of them to NEW.
_NEW_MARKERS: tuple[str, ...] = (
    "neu",
    "ovp",
    "versiegelt", "versiegelte", "versiegelter", "versiegeltes",
    "ungeöffnet", "ungeöffnete", "ungeöffneter", "ungeöffnetes",
    "originalverpackt", "originalverpackte", "originalverpackter",
    "unbenutzt", "unbenutzte", "unbenutzter", "unbenutztes",
)

#: German adjective endings are spelled out: sellers write "defekte Kamera" as
#: often as "Kamera defekt", and a strict word boundary would miss the former.
_DEFECTIVE_MARKERS: tuple[str, ...] = (
    "defekt", "defekte", "defekter", "defektes", "defekten",
    "kaputt", "kaputte", "kaputter", "kaputtes", "kaputten",
    "bastler",
    "ersatzteilträger",
)

#: Conditions this heuristic can actually decide. A rule carrying anything else
#: (LIKE_NEW, REFURBISHED — values older versions could store) keeps every ad
#: instead of silently returning nothing.
_DECIDABLE_CONDITIONS: frozenset[Condition] = frozenset(
    {Condition.NEW, Condition.USED, Condition.DEFECTIVE}
)


def _marker_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    """Build a word-boundary alternation for ``words``.

    Both boundaries matter: plain substring matching makes "neu" match
    "Neupreis" and "neuwertig", which would mark half of all used ads as new.
    """
    alternation = "|".join(re.escape(word) for word in words)
    return re.compile(rf"(?<![a-zäöüß])(?:{alternation})(?![a-zäöüß])")


_NEW_RE = _marker_pattern(_NEW_MARKERS)
_DEFECTIVE_RE = _marker_pattern(_DEFECTIVE_MARKERS)

#: A marker means its opposite when one of these stands shortly BEFORE it.
#: "ohne OVP" and "keine OVP" are among the most common phrases in used-ad
#: titles, and "nicht defekt" has exactly the same problem on the other side —
#: without this guard both of them counted as evidence FOR the marker.
_NEGATIONS_BEFORE: frozenset[str] = frozenset(
    {
        "ohne", "kein", "keine", "keinen", "keiner", "keinem", "keins",
        "keines", "nicht", "nichts", "nie", "niemals", "weder",
    }
)

#: ...and these cancel it from behind ("OVP fehlt", "OVP nicht mehr dabei",
#: "defekt? nein").
_NEGATIONS_AFTER: frozenset[str] = frozenset(
    {"fehlt", "fehlen", "fehlend", "nicht", "nein", "weg", "verloren", "entsorgt"}
)

#: How many words on each side the guard reads. Two covers "keine originale
#: OVP" and "OVP nicht mehr vorhanden" and is short enough that a negation
#: belonging to a different noun cannot reach the marker.
_NEGATION_WINDOW = 2

#: The guard never looks past a clause boundary: in "defekt, kein Bild" the
#: "kein" belongs to the photo, not to the defect in front of the comma.
_CLAUSE_BREAK_RE = re.compile(r"[.,;:!?()\[\]/\n\r·–—]")
_WORD_RE = re.compile(r"[a-zäöüß0-9]+")


def _is_negated(text: str, start: int, end: int) -> bool:
    """Whether the marker at ``text[start:end]`` is cancelled by its context."""
    clause_start = 0
    for brk in _CLAUSE_BREAK_RE.finditer(text, 0, start):
        clause_start = brk.end()
    tail = _CLAUSE_BREAK_RE.search(text, end)
    clause_end = tail.start() if tail else len(text)

    before = _WORD_RE.findall(text[clause_start:start])[-_NEGATION_WINDOW:]
    after = _WORD_RE.findall(text[end:clause_end])[:_NEGATION_WINDOW]
    return any(word in _NEGATIONS_BEFORE for word in before) or any(
        word in _NEGATIONS_AFTER for word in after
    )


def _has_marker(pattern: re.Pattern[str], text: str) -> bool:
    """True if ``text`` carries at least one marker that is not negated."""
    return any(
        not _is_negated(text, match.start(), match.end())
        for match in pattern.finditer(text)
    )


def guess_condition(title: str, description: str | None = None) -> Condition:
    """Best-effort item condition from the ad text.

    Defect wins over new, because "iPhone 14 neu, Display defekt" is a defect
    ad. Everything without a marker counts as USED: on a classifieds site
    second-hand is the default, and claiming NEW without evidence would be the
    more expensive mistake.
    """
    text = f"{title} {description or ''}".lower()
    if _has_marker(_DEFECTIVE_RE, text):
        return Condition.DEFECTIVE
    if _has_marker(_NEW_RE, text):
        return Condition.NEW
    return Condition.USED


def defect_markers(title: str, description: str | None = None) -> list[str]:
    """The words that made this ad look defective, in the order they appear.

    :func:`guess_condition` answers *whether*; a reader wants to know *why* —
    "defekt" in the description is worth seeing before writing to a seller.
    Negated markers are left out, so "nicht defekt" never shows up as evidence
    of a defect.
    """
    text = f"{title} {description or ''}".lower()
    found: list[str] = []
    for match in _DEFECTIVE_RE.finditer(text):
        if _is_negated(text, match.start(), match.end()):
            continue
        word = match.group(0).strip()
        if word and word not in found:
            found.append(word)
    return found


def matches_condition(
    wanted: Condition, title: str, description: str | None = None
) -> bool:
    """Whether an ad survives the rule's condition filter."""
    if wanted not in _DECIDABLE_CONDITIONS:
        return True
    guessed = guess_condition(title, description)
    if wanted is Condition.USED:
        # "Gebraucht" on a classifieds site means "not broken" — an ad that
        # never mentions its condition must not be thrown away.
        return guessed is not Condition.DEFECTIVE
    return guessed is wanted


def shipping_flag(item: ParsedListing) -> bool | None:
    """Whether a Kleinanzeigen card offers shipping, or None if unknowable.

    The parser decides this per card and states it in ``shipping_available``:
    the site prints its "Versand möglich" line inside the price/shipping block
    whenever the seller ships, so that block WITHOUT the line is a real "no".
    The block missing altogether is a third state — the markup changed — and
    answering "no shipping" there would silently empty a paid rule while the
    health monitor still reported the parser as healthy.

    ``shipping_cost == 0.0`` remains this parser's older marker for the same
    "Versand möglich" hint (a real shipping price would cost one extra request
    per ad), so a listing that carries only the marker still reads as a yes.
    No evidence at all is a shrug, and the unknown branch of
    :func:`matches_shipping` keeps the ad.
    """
    if item.shipping_available is not None:
        return item.shipping_available
    return True if item.shipping_cost is not None else None


def matches_shipping(wanted: bool | None, offered: bool | None) -> bool:
    """Tri-state shipping filter.

    An ad may only be dropped when BOTH sides are known. Treating unknown as a
    "no" would silently empty every marketplace that does not report the flag.
    """
    if wanted is None or offered is None:
        return True
    return wanted is offered


@register_parser
class KleinanzeigenParser(BaseParser):
    """Extracts offers from kleinanzeigen.de search result pages."""

    site = SiteName.KLEINANZEIGEN
    label = "Kleinanzeigen"
    requires_browser = False

    def __init__(self) -> None:
        super().__init__()
        # zip/city -> resolved Kleinanzeigen location id ("" = resolution failed)
        self._location_cache: dict[str, str] = {}

    # --- URL building -------------------------------------------------------
    def _build_url(
        self, query: SearchQuery, page: int = 1, location_id: str | None = None
    ) -> str:
        """Construct a Kleinanzeigen search URL.

        Format:
        ``/s-anzeige:angebote/sortierung:neueste/<preis:MIN:MAX>/<keywords>/k0[c..][l..][r..]``
        - ``anzeige:angebote`` hides wanted-ads (Gesuche).
        - ``sortierung:neueste`` puts the newest ads first (verified live).
        - The trailing token combines category, location and radius filters.
        """
        keywords = quote_plus(query.keywords.strip())
        segments = ["s-anzeige:angebote", "sortierung:neueste"]
        if query.min_price is not None or query.max_price is not None:
            lo = int(query.min_price) if query.min_price is not None else ""
            hi = int(query.max_price) if query.max_price is not None else ""
            segments.append(f"preis:{lo}:{hi}")
        segments.append(keywords)
        page_seg = "" if page <= 1 else f"seite:{page}/"

        suffix = "k0"
        if query.category and query.category in CATEGORY_IDS:
            suffix += f"c{CATEGORY_IDS[query.category]}"
        if location_id:
            suffix += f"l{location_id}"
            if query.max_distance_km:
                suffix += f"r{int(query.max_distance_km)}"

        path = "/".join(segments)
        return f"{BASE_URL}/{path}/{page_seg}{suffix}"

    # --- Location resolution --------------------------------------------------
    async def resolve_location_id(self, query: SearchQuery) -> str | None:
        """Resolve a zip code / city name to Kleinanzeigen's internal l-id.

        Uses the site's own autocomplete endpoint. Any failure degrades to a
        Germany-wide search (returns None) instead of raising.
        """
        term = (query.zip_code or query.location or "").strip()
        if not term:
            return None
        if term in self._location_cache:
            return self._location_cache[term] or None

        loc_id = ""
        try:
            resp = await self.fetch(
                f"{BASE_URL}/s-ort-empfehlungen.json", params={"query": term}
            )
            data = resp.json()
            loc_id = self._extract_location_id(data) or ""
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logger.warning("[kleinanzeigen] location lookup failed for {!r}: {}", term, exc)

        self._location_cache[term] = loc_id
        if loc_id:
            logger.info("[kleinanzeigen] resolved {!r} -> location id {}", term, loc_id)
        else:
            logger.info("[kleinanzeigen] no location id for {!r}; searching nationwide", term)
            try:
                from html import escape as _esc

                from app.services import health  # lazy: avoid import cycles

                await health.report(
                    f"loc:{term}",
                    f"⚠️ Kleinanzeigen: Ort <b>{_esc(term)}</b> konnte nicht aufgelöst "
                    "werden — die Umkreissuche ist inaktiv, es wird "
                    "deutschlandweit gesucht! PLZ in der Suchregel prüfen.",
                )
            except Exception:  # noqa: BLE001
                pass
        return loc_id or None

    @staticmethod
    def _extract_location_id(data: object) -> str | None:
        """Pull the location id out of the autocomplete payload.

        Live shape (verified 2026-07): the id is embedded in the dict KEY with
        an underscore prefix, the value is only the display label::

            {"_0": "Deutschland", "_5198": "67550 Worms"}

        ``_0`` is the nationwide pseudo-entry and must be skipped. Older/other
        shapes (label->"l<id>" values, lists of objects with an ``id`` field)
        are still handled as fallbacks.
        """
        if isinstance(data, dict):
            # Current shape: id in the key as "_<id>"; entries are relevance-
            # sorted, so the first non-zero id is the best match.
            for key in data:
                match = re.fullmatch(r"_(\d+)", str(key).strip())
                if match and match.group(1) != "0":
                    return match.group(1)
            # Legacy shape: label keys, "l<id>" (or bare id) values.
            for value in data.values():
                text = str(value).strip()
                match = re.fullmatch(r"l?(\d{3,})", text)
                if match:
                    return match.group(1)
                match = re.search(r"l(\d{3,})", text)
                if match:
                    return match.group(1)
            return None

        if isinstance(data, list):
            candidates: list[str] = []
            for entry in data:
                if isinstance(entry, dict):
                    if "id" in entry:
                        candidates.append(str(entry["id"]))
                    candidates.extend(
                        str(v) for k, v in entry.items() if k != "id"
                    )
                else:
                    candidates.append(str(entry))
            for text in candidates:
                match = re.fullmatch(r"l?(\d{3,})", text.strip())
                if match:
                    return match.group(1)
            for text in candidates:
                match = re.search(r"l(\d{3,})", text)
                if match:
                    return match.group(1)
        return None

    # --- Main entrypoint ----------------------------------------------------
    async def search(self, query: SearchQuery) -> list[ParsedListing]:
        location_id = await self.resolve_location_id(query)
        url = self._build_url(query, location_id=location_id)
        logger.debug("[kleinanzeigen] GET {}", url)
        html = await self.fetch_text(url)
        listings = self._parse_results(html, query)

        # Client-side filtering the site URL can't express.
        filtered: list[ParsedListing] = []
        for item in listings:
            if not query.matches_text(item.title, item.description):
                continue
            if query.exclude_auctions and item.is_auction:
                continue
            if not matches_condition(query.condition, item.title, item.description):
                continue
            if not matches_shipping(query.shipping_available, shipping_flag(item)):
                continue
            if not query.matches_vehicle(item.mileage_km, item.registration_year):
                continue
            if query.max_price is not None and item.price is not None:
                if item.price > query.max_price:
                    continue
            if query.min_price is not None and item.price is not None:
                if item.price < query.min_price:
                    continue
            filtered.append(item)
            if len(filtered) >= query.max_results:
                break
        return filtered

    # --- HTML extraction ----------------------------------------------------
    #: Markup that only a real result page has. If none of it is present and
    #: no cards were found, we were served something else (captcha, error,
    #: layout change) — not an honest "nothing matched".
    _RESULT_PAGE_MARKERS = (
        "#srchrslt-adtable",
        ".srp-pagination",
        "#srchrslt-content",
        ".messagebox--alert",   # site's own "keine Anzeigen gefunden" box
    )

    def _parse_results(self, html: str, query: SearchQuery) -> list[ParsedListing]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article.aditem")
        if not cards and not any(
            soup.select_one(marker) for marker in self._RESULT_PAGE_MARKERS
        ):
            self.mark_suspected_block()
        results: list[ParsedListing] = []
        for card in cards:
            try:
                parsed = self._parse_card(card)
            except Exception as exc:  # noqa: BLE001 - skip malformed card
                logger.debug("[kleinanzeigen] skipped a card: {}", exc)
                continue
            if parsed is not None:
                results.append(parsed)
        return results

    def _parse_card(self, card: Tag) -> ParsedListing | None:
        external_id = card.get("data-adid") or card.get("data-href", "")
        if isinstance(external_id, str):
            external_id = external_id.strip("/").split("/")[-1].split("-")[0]
        if not external_id:
            return None

        # --- Link + title ---
        link = card.select_one("a.ellipsis") or card.select_one("h2 a")
        if link is None:
            return None
        title = link.get_text(strip=True)
        href = link.get("href", "")
        url = urljoin(BASE_URL, href) if isinstance(href, str) else BASE_URL

        # --- Price ---
        price_el = card.select_one(".aditem-main--middle--price-shipping--price")
        price = self._parse_price(price_el.get_text() if price_el else None)

        # --- Shipping hint ---
        # Two different absences: the price/shipping BLOCK is missing (the site
        # changed its markup — we know nothing), or the block is there without
        # the "Versand möglich" line, which is the site's way of saying the
        # seller does not ship. That difference decides whether a "shipping
        # only" rule keeps working or silently returns nothing.
        shipping_box = card.select_one(".aditem-main--middle--price-shipping")
        shipping_el = card.select_one(
            ".aditem-main--middle--price-shipping--shipping"
        )
        shipping_text = shipping_el.get_text(strip=True).lower() if shipping_el else ""
        offers_shipping = "versand" in shipping_text
        shipping_known = shipping_box is not None

        # --- Location ---
        loc_el = card.select_one(".aditem-main--top--left")
        location = loc_el.get_text(strip=True) if loc_el else None

        # --- Description ---
        desc_el = card.select_one(".aditem-main--middle--description")
        description = desc_el.get_text(strip=True) if desc_el else None

        # --- Attribute tags (verified live 2026-07): vehicle cards carry
        # "74.000 km" and "EZ 12/2020" as simpletag spans. Prepending them to
        # the description surfaces them on the deal card and keeps them
        # searchable — without any schema change.
        tags = [t.get_text(strip=True) for t in card.select("span.simpletag")]
        tags = [tag for tag in tags if tag]
        mileage_km, registration_year = self._parse_vehicle_tags(tags)
        if tags:
            attr_line = " · ".join(tags[:4])
            description = (
                f"{attr_line} — {description}" if description else attr_line
            )

        # --- Image ---
        image_url = self._extract_image(card)

        # --- Posting date ("Heute, 08:01" / "Gestern, 21:08" / "04.07.2026").
        # Promoted TOP ads have an empty date container -> posted_at stays None
        # and the freshness filter treats them as old.
        date_el = card.select_one(".aditem-main--top--right")
        posted_at = self._parse_posted_date(
            date_el.get_text(strip=True) if date_el else None
        )

        # --- Auction / negotiable detection from price text ---
        raw_price_text = price_el.get_text(strip=True).lower() if price_el else ""
        is_auction = "gebot" in raw_price_text  # "X € VB" is not an auction
        # "VB" = Verhandlungsbasis: the asking price is soft, which is exactly
        # what a flipper wants to know before writing to the seller.
        is_negotiable = "vb" in raw_price_text.split() or raw_price_text.endswith("vb")

        return ParsedListing(
            site=self.site,
            external_id=str(external_id),
            title=title or "(kein Titel)",
            url=url,
            price=price,
            currency="EUR",
            shipping_cost=0.0 if offers_shipping else None,
            shipping_available=offers_shipping if shipping_known else None,
            image_url=image_url,
            description=description,
            location=location,
            condition=Condition.ANY,
            is_auction=is_auction,
            is_negotiable=is_negotiable,
            posted_at=posted_at,
            mileage_km=mileage_km,
            registration_year=registration_year,
        )

    # --- Small helpers ------------------------------------------------------
    @staticmethod
    def _parse_vehicle_tags(tags: list[str]) -> tuple[int | None, int | None]:
        """Extract mileage (km) and first-registration year from card tags.

        Live formats (verified 2026): ``"74.000 km"`` and ``"EZ 12/2020"`` /
        ``"EZ 2020"``. Returns ``(None, None)`` for non-vehicle listings.
        """
        mileage: int | None = None
        year: int | None = None
        for tag in tags:
            low = tag.lower()
            if mileage is None and "km" in low:
                digits = re.sub(r"[^\d]", "", tag)
                if digits:
                    value = int(digits)
                    # Plausible car mileage; ignore e.g. "5 km entfernt".
                    if 100 <= value <= 1_000_000:
                        mileage = value
            if year is None and ("ez" in low or "erstzulassung" in low):
                match = re.search(r"(19|20)\d{2}", tag)
                if match:
                    year = int(match.group(0))
        return mileage, year

    @staticmethod
    def _parse_posted_date(text: str | None) -> datetime | None:
        """Parse the card's posting date.

        Live formats (verified 2026-07): ``"Heute, 08:01"``, ``"Gestern,
        21:08"`` and ``"04.07.2026"`` for older ads. Promoted TOP ads ship an
        empty container -> ``None``.
        """
        if not text:
            return None
        text = text.strip()
        # "Heute" means today in Germany, not in the container's timezone.
        now = local_now()
        try:
            lower = text.lower()
            time_match = re.search(r"(\d{1,2}):(\d{2})", text)
            hour, minute = (
                (int(time_match.group(1)), int(time_match.group(2)))
                if time_match
                else (12, 0)
            )
            if lower.startswith("heute"):
                return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if lower.startswith("gestern"):
                base = now - timedelta(days=1)
                return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            date_match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
            if date_match:
                day, month, year = (int(g) for g in date_match.groups())
                return datetime(year, month, day, 12, 0)
        except (ValueError, OverflowError):
            return None
        return None

    @staticmethod
    def _parse_price(text: str | None) -> float | None:
        if not text:
            return None
        # Examples: "1.300 €", "1.300 € VB", "Zu verschenken", "VB"
        cleaned = text.replace(".", "").replace("\xa0", " ")
        match = re.search(r"(\d+(?:,\d{1,2})?)", cleaned)
        if not match:
            return None
        return float(match.group(1).replace(",", "."))

    @staticmethod
    def _extract_image(card: Tag) -> str | None:
        img = card.select_one("img")
        if img is None:
            return None
        for attr in ("src", "data-imgsrc", "data-src"):
            val = img.get(attr)
            if isinstance(val, str) and val.startswith("http"):
                return val
        srcset = img.get("srcset")
        if isinstance(srcset, str) and srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first.startswith("http"):
                return first
        return None
