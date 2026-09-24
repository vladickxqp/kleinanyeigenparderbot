"""Parser for kleinanzeigen.de (formerly eBay Kleinanzeigen).

This is the reference implementation. It builds an SEO search URL, fetches the
result page with the polite base-class HTTP client and extracts listings from the
result cards. HTML structure on classifieds sites changes over time — the
selectors below are defensive and degrade gracefully (a missing field yields
``None`` rather than an exception).

Two layouts are read. The classic one names every field with a stable class
(``article.aditem``, ``.aditem-main--middle--price-shipping--price`` …). The
2026 layout is built from utility classes (``flex``, ``text-title3``) that carry
no meaning and change with every restyle, so for it nothing is looked up by
class: the card is ``article[data-adid]``, the title is the heading's link, and
price, date, location, shipping and vehicle tags are recognised by what they
SAY — "250 € VB", "Heute, 12:05", "Versand möglich", "55.000 km". Both paths
are exercised by fixtures in ``tests/test_kleinanzeigen_parser.py`` and
``tests/test_kleinanzeigen_layout_2026.py``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
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
    #: layout change) — not an honest "nothing matched". Both layouts are
    #: listed: the 2026 page keeps ``body#srchrslt`` and the price inputs even
    #: when the ``ul`` lost its id.
    _RESULT_PAGE_MARKERS = (
        "#srchrslt-adtable",
        "#srp-results",
        "body#srchrslt",
        "body#srp",
        "[id^='srchrslt-brwse']",
        ".srp-pagination",
        "#srchrslt-content",
        "a[href*='seite:2']",
        ".messagebox--alert",   # site's own "keine Anzeigen gefunden" box
    )
    #: A result card in any layout. ``data-adid`` outlived every restyle;
    #: the ``aditem`` class did not, and the ``srp`` page uses ``li``.
    _CARD_SELECTOR = "article[data-adid], li[data-adid], article.aditem"

    def _parse_results(self, html: str, query: SearchQuery) -> list[ParsedListing]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(self._CARD_SELECTOR)
        if not cards and not any(
            soup.select_one(marker) for marker in self._RESULT_PAGE_MARKERS
        ):
            self.mark_suspected_block()
        results: list[ParsedListing] = []
        seen: set[str] = set()
        for card in cards:
            # The ``srp`` page's <li> items are not closed, so the parser nests
            # every card inside the one before it. Cut the nested cards out of
            # this one before reading it, or its text would carry the whole
            # rest of the page — and "Versand möglich" three ads down would
            # become this ad's shipping. The cut-out cards keep their own
            # subtree and are read in their own turn.
            for nested in card.select("[data-adid]"):
                nested.extract()
            try:
                parsed = self._parse_card(card)
            except Exception as exc:  # noqa: BLE001 - skip malformed card
                logger.debug("[kleinanzeigen] skipped a card: {}", exc)
                continue
            if parsed is not None and parsed.external_id not in seen:
                seen.add(parsed.external_id)
                results.append(parsed)
        return results

    def _parse_card(self, card: Tag) -> ParsedListing | None:
        external_id = card.get("data-adid") or card.get("data-href", "")
        if isinstance(external_id, str):
            external_id = external_id.strip("/").split("/")[-1].split("-")[0]
        if not external_id:
            return None

        # --- Link + title ---
        link = self._title_link(card)
        title = self._title(card, link)
        if not title:
            return None
        href = card.get("data-href") or (link.get("href", "") if link is not None else "")
        url = urljoin(BASE_URL, href) if isinstance(href, str) and href else BASE_URL

        # --- Price ---
        price_text = self._price_text(card)
        price = self._parse_price(price_text)

        # --- Shipping hint ---
        # Two different absences: the site said nothing (markup we do not
        # know — unknown), or it said "Nur Abholung" / left the shipping line
        # off its price block, which is its way of saying the seller does not
        # ship. That difference decides whether a "shipping only" rule keeps
        # working or silently returns nothing.
        offers_shipping, shipping_known = self._shipping(card)

        # --- Location ---
        location = self._location(card)

        # --- Description ---
        description = self._description(card, link)

        # --- Attribute tags (verified live 2026-07 / 2026-09): vehicle cards
        # carry "74.000 km" and "EZ 12/2020". Prepending them to the
        # description surfaces them on the deal card and keeps them
        # searchable — without any schema change.
        tags = self._tags(card)
        mileage_km, registration_year = self._parse_vehicle_tags(tags)
        if tags:
            attr_line = " · ".join(tags[:4])
            description = (
                f"{attr_line} — {description}" if description else attr_line
            )

        # --- Image ---
        image_url = self._extract_image(card)

        # --- Posting date ("Heute, 08:01" / "Gestern, 21:08" / "04.07.2026").
        # Promoted TOP/PRO ads show no date -> posted_at stays None and the
        # freshness filter treats them as old.
        posted_at = self._parse_posted_date(self._date_text(card))

        # --- Auction / negotiable detection from price text ---
        raw_price_text = (price_text or "").strip().lower()
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

    @classmethod
    def _extract_image(cls, card: Tag) -> str | None:
        # The 2026 card embeds an ImageObject whose contentUrl is the large
        # rendition; the <img> itself is a thumbnail.
        content_url = cls._json_ld(card).get("contentUrl")
        if isinstance(content_url, str) and content_url.startswith("http"):
            return content_url
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

    # --- Field lookup across both layouts ------------------------------------
    # Classic layout first (a stable class), then the 2026 layout by what the
    # text says. Nothing below matches a utility class.

    #: "250 €", "1.150 € VB", "VB", "Zu verschenken" — the whole text of a
    #: price element, nothing else. Anchored so a description sentence
    #: mentioning a price never becomes THE price.
    _PRICE_RE = re.compile(
        r"^(?:\d[\d.]*(?:,\d{1,2})?\s*€(?:\s*VB)?|VB|Zu verschenken)$", re.I
    )
    _DATE_RE = re.compile(
        r"^(?:heute|gestern),?\s*\d{1,2}:\d{2}$|^\d{2}\.\d{2}\.\d{4}$", re.I
    )
    _TAG_RE = re.compile(
        r"^\d[\d.]*\s*km$|^EZ\s?\d{2}/\d{4}$|^EZ\s?\d{4}$|^Erstzulassung\b", re.I
    )
    _ZIP_CITY_RE = re.compile(r"^\d{5}\s+\S")
    #: Longer than this and a text node is prose, not a field.
    _SHORT_TEXT = 48

    @classmethod
    def _short_texts(
        cls, card: Tag, *, skip_description: bool = False
    ) -> list[tuple[str, Tag]]:
        """Every short text node in the card with its parent element.

        With ``skip_description`` the ad's own prose is left out, so a seller's
        sentence never passes for a date, a shipping marker or a vehicle tag.
        """
        prose: list[Tag] = (
            card.select(cls._DESCRIPTION_SELECTOR) if skip_description else []
        )
        found: list[tuple[str, Tag]] = []
        for node in card.descendants:
            if not isinstance(node, NavigableString) or isinstance(node, Comment):
                continue
            parent = node.parent
            if parent is None or parent.name in ("script", "style"):
                continue
            if prose and any(parent is box or box in parent.parents for box in prose):
                continue
            text = re.sub(r"\s+", " ", str(node)).strip()
            if text and len(text) <= cls._SHORT_TEXT:
                found.append((text, parent))
        return found

    @staticmethod
    def _json_ld(card: Tag) -> dict:
        """The card's embedded schema.org object, or an empty dict."""
        script = card.select_one("script[type='application/ld+json']")
        if script is None:
            return {}
        try:
            data = json.loads(script.get_text() or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _title_link(card: Tag) -> Tag | None:
        for selector in ("a.ellipsis", "h2 a", "h3 a", ".adlist--item--boldtitle a"):
            link = card.select_one(selector)
            if link is not None and link.get_text(strip=True):
                return link
        # Whole-card links: the image link's only text is the photo count, so
        # take the link that says the most and carries no image.
        best: Tag | None = None
        for link in card.select("a[href*='/s-anzeige/']"):
            if link.select_one("img") is not None:
                continue
            text = link.get_text(strip=True)
            if text and (best is None or len(text) > len(best.get_text(strip=True))):
                best = link
        return best

    @classmethod
    def _title(cls, card: Tag, link: Tag | None) -> str:
        if link is not None:
            return link.get_text(strip=True)
        # 2026 cards whose whole surface is the link: the heading holds the
        # title as plain text, and the embedded object repeats it.
        for selector in ("h2", "h3", ".adlist--item--boldtitle"):
            heading = card.select_one(selector)
            if heading is not None and heading.get_text(strip=True):
                return heading.get_text(" ", strip=True)
        embedded = cls._json_ld(card).get("title")
        return embedded.strip() if isinstance(embedded, str) else ""

    @classmethod
    def _price_text(cls, card: Tag) -> str | None:
        for selector in (".aditem-main--middle--price-shipping--price", ".adlist--item--price"):
            classic = card.select_one(selector)
            if classic is not None:
                return classic.get_text(strip=True)
        for text, _parent in cls._short_texts(card):
            if cls._PRICE_RE.match(text):
                return text
        return None

    @classmethod
    def _shipping(cls, card: Tag) -> tuple[bool, bool]:
        """(offers shipping, the site said so either way).

        Only the site's own markers count. The DESCRIPTION is left out: a
        seller writing "kein Versand" or "Versandkosten 8 €" is prose, and
        the tri-state filter must not drop an ad on a sentence it half-read.
        """
        box = card.select_one(".aditem-main--middle--price-shipping")
        if box is not None:
            line = card.select_one(".aditem-main--middle--price-shipping--shipping")
            text = line.get_text(strip=True).lower() if line else ""
            return "versand" in text, True
        for text, _parent in cls._short_texts(card, skip_description=True):
            low = text.lower()
            if low == "versand möglich":
                return True, True
            if low == "nur abholung":
                return False, True
        return False, False

    @classmethod
    def _location(cls, card: Tag) -> str | None:
        for selector in (".aditem-main--top--left", ".adlist--item--info--location"):
            classic = card.select_one(selector)
            if classic is not None:
                return classic.get_text(strip=True) or None
        # The 2026 card marks the place with a pin icon; the text sits next to it.
        pin = card.select_one("svg[data-title='locationOutline']")
        if pin is not None and pin.parent is not None:
            text = pin.parent.get_text(" ", strip=True)
            if text:
                return text
        for text, _parent in cls._short_texts(card):
            if cls._ZIP_CITY_RE.match(text):
                return text
        return None

    @classmethod
    def _date_text(cls, card: Tag) -> str | None:
        for selector in (".aditem-main--top--right", ".adlist--item--info--date"):
            classic = card.select_one(selector)
            if classic is not None:
                return classic.get_text(strip=True) or None
        for text, _parent in cls._short_texts(card, skip_description=True):
            if cls._DATE_RE.match(text):
                return text
        return None

    #: Elements that hold the ad's own prose; field lookups by text skip them.
    _DESCRIPTION_SELECTOR = (
        ".aditem-main--middle--description, .adlist--item--description, "
        ".long-description, .description-preview"
    )

    @classmethod
    def _description(cls, card: Tag, link: Tag | None) -> str | None:
        classic = card.select_one(".aditem-main--middle--description")
        if classic is not None:
            return classic.get_text(strip=True) or None
        # The srp page ships the full text behind a "..." button.
        full = card.select_one(".adlist--item--description .long-description")
        if full is not None:
            for br in full.select("br"):
                br.replace_with("\n")
            text = "\n".join(
                line.strip() for line in full.get_text().splitlines() if line.strip()
            )
            if text:
                return text
        preview = card.select_one(".adlist--item--description")
        if preview is not None:
            for button in preview.select("button"):
                button.extract()
            text = preview.get_text(" ", strip=True)
            if text:
                return text
        # 2026 utility-class card: the paragraph right under the heading, and
        # the embedded ImageObject's description — take whichever says more,
        # because the defect is usually in the words the teaser cut off.
        candidates: list[str] = []
        heading = link.find_parent(["h2", "h3"]) if link is not None else card.select_one("h2, h3")
        paragraph = heading.find_next_sibling("p") if heading is not None else None
        if paragraph is not None:
            candidates.append(paragraph.get_text(" ", strip=True))
        embedded = cls._json_ld(card).get("description")
        if isinstance(embedded, str):
            candidates.append(re.sub(r"\s+", " ", embedded).strip())
        candidates = [c for c in candidates if c]
        return max(candidates, key=len) if candidates else None

    @classmethod
    def _tags(cls, card: Tag) -> list[str]:
        classic = [t.get_text(strip=True) for t in card.select("span.simpletag")]
        classic = [tag for tag in classic if tag]
        if classic:
            return classic
        tags: list[str] = []
        for text, _parent in cls._short_texts(card, skip_description=True):
            if cls._TAG_RE.match(text) and text not in tags:
                tags.append(text)
        return tags
