"""Parser for idealo.de (price-comparison portal, JS-heavy → Playwright).

Idealo loads its result list client-side and has bot protection, so this parser
renders the page in a headless browser via ``fetch_rendered``. Idealo's markup
changes frequently; selectors are defensive and a missing field degrades to
``None`` rather than raising. Adjust the selectors below if the layout shifts.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag
from loguru import logger

from app.database.models.enums import Condition, SiteName
from app.parsers.base import BaseParser
from app.parsers.registry import register_parser
from app.parsers.schemas import ParsedListing, SearchQuery

BASE_URL = "https://www.idealo.de"
_RESULT_SELECTOR = "[data-testid='resultItem'], .sr-resultList__item"

#: Conditions a price-comparison portal cannot serve. Answering such a rule
#: with brand-new retail offers would pull the 30-day market median — which the
#: whole deal score rests on — up to shop level and make every real second-hand
#: bargain look ordinary.
_UNAVAILABLE_CONDITIONS = (Condition.USED, Condition.DEFECTIVE)


@register_parser
class IdealoParser(BaseParser):
    """Extracts product offers from idealo.de search results."""

    site = SiteName.IDEALO
    label = "Idealo"
    requires_browser = True

    def _build_url(self, query: SearchQuery) -> str:
        return f"{BASE_URL}/preisvergleich/MainSearchProductCategory.html?q={quote_plus(query.keywords)}"

    async def search(self, query: SearchQuery) -> list[ParsedListing]:
        if query.condition in _UNAVAILABLE_CONDITIONS:
            logger.debug(
                "[idealo] skipped: rule asks for {} offers, Idealo lists new "
                "retail only", query.condition.value,
            )
            return []

        url = self._build_url(query)
        logger.debug("[idealo] render {}", url)
        html = await self.fetch_rendered(url, wait_selector=_RESULT_SELECTOR)
        listings = self._parse_results(html)

        result: list[ParsedListing] = []
        for item in listings:
            if not query.matches_text(item.title):
                continue
            if query.max_price is not None and item.price and item.price > query.max_price:
                continue
            if query.min_price is not None and item.price and item.price < query.min_price:
                continue
            result.append(item)
            if len(result) >= query.max_results:
                break
        return result

    def _parse_results(self, html: str) -> list[ParsedListing]:
        soup = BeautifulSoup(html, "lxml")
        results: list[ParsedListing] = []
        for card in soup.select(_RESULT_SELECTOR):
            try:
                parsed = self._parse_card(card)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[idealo] skipped card: {}", exc)
                continue
            if parsed is not None:
                results.append(parsed)
        return results

    def _parse_card(self, card: Tag) -> ParsedListing | None:
        link = card.select_one("a[href]")
        if link is None:
            return None
        href = link.get("href", "")
        url = href if isinstance(href, str) and href.startswith("http") else BASE_URL + str(href)

        title_el = card.select_one(
            "[data-testid='resultItemName'], .sr-productSummary__title, .offerList-item-description-title"
        )
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
        if not title:
            return None

        external_id = self._extract_id(url, card)
        if not external_id:
            return None

        price_el = card.select_one(
            "[data-testid='detailedPriceInfo__price'], .sr-detailedPriceInfo__price, .price"
        )
        price = self._parse_price(price_el.get_text() if price_el else None)

        img = card.select_one("img")
        image_url = None
        if img is not None:
            for attr in ("src", "data-src"):
                val = img.get(attr)
                if isinstance(val, str) and val.startswith("http"):
                    image_url = val
                    break

        return ParsedListing(
            site=self.site,
            external_id=external_id,
            title=title,
            url=url,
            price=price,
            currency="EUR",
            image_url=image_url,
            condition=Condition.NEW,  # Idealo lists new-product offers
        )

    @staticmethod
    def _extract_id(url: str, card: Tag) -> str | None:
        data_id = card.get("data-item-id") or card.get("id")
        if isinstance(data_id, str) and data_id.strip():
            return data_id.strip()
        match = re.search(r"/(?:preisvergleich/)?[^/]*?(\d{5,})", url)
        return match.group(1) if match else None

    @staticmethod
    def _parse_price(text: str | None) -> float | None:
        if not text:
            return None
        cleaned = text.replace(".", "").replace("\xa0", " ")
        match = re.search(r"(\d+(?:,\d{1,2})?)", cleaned)
        if not match:
            return None
        return float(match.group(1).replace(",", "."))
