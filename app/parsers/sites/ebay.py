"""Parser for ebay.de search result pages (httpx + BeautifulSoup).

eBay renders search results server-side, so no browser is required. Selectors
target the classic ``li.s-item`` result cards.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag
from loguru import logger

from app.config.settings import settings
from app.database.models.enums import Condition, SiteName
from app.parsers.base import BaseParser
from app.parsers.registry import register_parser
from app.parsers.schemas import ParsedListing, SearchQuery

BASE_URL = "https://www.ebay.de"


#: Category slug (SearchRule.category) -> eBay category id (_sacat parameter).
CATEGORY_IDS: dict[str, str] = {
    "handys": "9355",         # Handys & Smartphones
    "notebooks": "175672",    # Notebooks & Netbooks
    "pc-zubehoer": "27386",   # Grafikkarten
    "konsolen": "139971",     # Spielekonsolen
}

#: Rule condition -> eBay's ``LH_ItemCondition`` facet value. These are eBay's
#: own global ConditionIDs, the very table 1000/3000 already came from; 7000 is
#: "Defekt oder nur Teile" ("For parts or not working"). Without the last entry
#: a defect hunt was answered with ordinary working items, because eBay applies
#: no condition facet at all when the parameter is missing.
CONDITION_IDS: dict[Condition, int] = {
    Condition.NEW: 1000,
    Condition.USED: 3000,
    Condition.DEFECTIVE: 7000,
}


class EbayParser(BaseParser):
    """Extracts offers from ebay.de search results.

    Registered at the bottom of the module, behind ``settings.ebay_enabled``:
    eBay refuses every scrape with HTTP 403, and a parser that never delivers
    must not sit in the picker or spend a request per run on every "all
    sites" rule.
    """

    site = SiteName.EBAY
    label = "eBay"
    requires_browser = False

    def _build_url(self, query: SearchQuery) -> str:
        params: dict[str, str | int] = {"_nkw": query.keywords, "_ipg": 60}
        if query.max_price is not None:
            params["_udhi"] = int(query.max_price)
        if query.min_price is not None:
            params["_udlo"] = int(query.min_price)
        condition_id = CONDITION_IDS.get(query.condition)
        if condition_id is not None:
            params["LH_ItemCondition"] = condition_id
        if query.exclude_auctions:
            params["LH_BIN"] = 1  # Buy-It-Now only
        if query.category and query.category in CATEGORY_IDS:
            params["_sacat"] = CATEGORY_IDS[query.category]
        return f"{BASE_URL}/sch/i.html?{urlencode(params)}"

    async def search(self, query: SearchQuery) -> list[ParsedListing]:
        url = self._build_url(query)
        logger.debug("[ebay] GET {}", url)
        html = await self.fetch_text(url)
        listings = self._parse_results(html)

        # query.shipping_available is deliberately NOT enforced here: eBay's
        # result cards never state whether an item ships, and filtering on an
        # unknown value would return zero results for every rule that sets it.
        result: list[ParsedListing] = []
        for item in listings:
            if not query.matches_text(item.title):
                continue
            if query.max_price is not None and item.price and item.price > query.max_price:
                continue
            result.append(item)
            if len(result) >= query.max_results:
                break
        return result

    def _parse_results(self, html: str) -> list[ParsedListing]:
        soup = BeautifulSoup(html, "lxml")
        results: list[ParsedListing] = []
        for card in soup.select("li.s-item"):
            try:
                parsed = self._parse_card(card)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[ebay] skipped card: {}", exc)
                continue
            if parsed is not None:
                results.append(parsed)
        return results

    def _parse_card(self, card: Tag) -> ParsedListing | None:
        link = card.select_one("a.s-item__link")
        title_el = card.select_one(".s-item__title")
        if link is None or title_el is None:
            return None
        title = title_el.get_text(strip=True)
        # eBay prepends a promo card titled "Shop on eBay" — skip it.
        if not title or title.lower() in {"shop on ebay", "neues angebot"}:
            return None

        href = link.get("href", "")
        url = href if isinstance(href, str) and href.startswith("http") else BASE_URL
        external_id = self._extract_item_id(url)
        if not external_id:
            return None

        price_el = card.select_one(".s-item__price")
        price = self._parse_price(price_el.get_text() if price_el else None)

        img = card.select_one(".s-item__image-wrapper img") or card.select_one("img")
        image_url = None
        if img is not None:
            for attr in ("src", "data-src"):
                val = img.get(attr)
                if isinstance(val, str) and val.startswith("http"):
                    image_url = val
                    break

        subtitle = card.select_one(".s-item__subtitle")
        is_auction = bool(subtitle and "gebot" in subtitle.get_text().lower())

        loc_el = card.select_one(".s-item__location, .s-item__itemLocation")
        location = loc_el.get_text(strip=True) if loc_el else None

        return ParsedListing(
            site=self.site,
            external_id=external_id,
            title=title,
            url=url,
            price=price,
            currency="EUR",
            image_url=image_url,
            location=location,
            condition=Condition.ANY,
            is_auction=is_auction,
        )

    @staticmethod
    def _extract_item_id(url: str) -> str | None:
        match = re.search(r"/itm/(?:.*?/)?(\d{9,})", url)
        return match.group(1) if match else None

    @staticmethod
    def _parse_price(text: str | None) -> float | None:
        if not text:
            return None
        # e.g. "EUR 1.199,00", "1.199,00 €", "EUR 800,00 bis EUR 1.200,00"
        cleaned = text.replace(".", "").replace("\xa0", " ")
        match = re.search(r"(\d+(?:,\d{1,2})?)", cleaned)
        if not match:
            return None
        return float(match.group(1).replace(",", "."))


# Off by default: see settings.ebay_enabled. A rule with no sites chosen
# resolves to EVERY registered parser, which is how a dead marketplace reaches
# all existing users on the next deploy.
if settings.ebay_enabled:
    register_parser(EbayParser)
