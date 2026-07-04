"""Parser for kleinanzeigen.de (formerly eBay Kleinanzeigen).

This is the reference implementation. It builds an SEO search URL, fetches the
result page with the polite base-class HTTP client and extracts listings from the
``article.aditem`` cards. HTML structure on classifieds sites changes over time —
the selectors below are defensive and degrade gracefully (a missing field yields
``None`` rather than an exception).
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup, Tag
from loguru import logger

from app.database.models.enums import Condition, SiteName
from app.parsers.base import BaseParser
from app.parsers.registry import register_parser
from app.parsers.schemas import ParsedListing, SearchQuery

BASE_URL = "https://www.kleinanzeigen.de"


@register_parser
class KleinanzeigenParser(BaseParser):
    """Extracts offers from kleinanzeigen.de search result pages."""

    site = SiteName.KLEINANZEIGEN
    label = "Kleinanzeigen"
    requires_browser = False

    # --- URL building -------------------------------------------------------
    def _build_url(self, query: SearchQuery, page: int = 1) -> str:
        """Construct a Kleinanzeigen search URL.

        Format: ``/s-<price-segment>/<keywords>/k0`` where the price segment is
        ``preis:MIN:MAX``. Missing bounds are left blank (``preis:100:`` etc.).
        """
        keywords = quote_plus(query.keywords.strip())
        segments = ["s"]
        if query.min_price is not None or query.max_price is not None:
            lo = int(query.min_price) if query.min_price is not None else ""
            hi = int(query.max_price) if query.max_price is not None else ""
            segments.append(f"preis:{lo}:{hi}")
        segments.append(keywords)
        page_seg = "" if page <= 1 else f"seite:{page}/"
        path = "/".join(segments)
        return f"{BASE_URL}/{path}/{page_seg}k0"

    # --- Main entrypoint ----------------------------------------------------
    async def search(self, query: SearchQuery) -> list[ParsedListing]:
        url = self._build_url(query)
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

        # --- Image ---
        image_url = self._extract_image(card)

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
        )

    # --- Small helpers ------------------------------------------------------
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
