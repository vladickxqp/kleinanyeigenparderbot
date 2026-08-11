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
    def _parse_results(self, html: str, query: SearchQuery) -> list[ParsedListing]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article.aditem")
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
        shipping_el = card.select_one(
            ".aditem-main--middle--price-shipping--shipping"
        )
        shipping_text = shipping_el.get_text(strip=True).lower() if shipping_el else ""
        shipping_available = "versand" in shipping_text

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

        return ParsedListing(
            site=self.site,
            external_id=str(external_id),
            title=title or "(kein Titel)",
            url=url,
            price=price,
            currency="EUR",
            shipping_cost=0.0 if shipping_available else None,
            image_url=image_url,
            description=description,
            location=location,
            condition=Condition.ANY,
            is_auction=is_auction,
            posted_at=posted_at,
        )

    # --- Small helpers ------------------------------------------------------
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
        now = datetime.now()
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
