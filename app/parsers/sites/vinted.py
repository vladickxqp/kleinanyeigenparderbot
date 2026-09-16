"""Parser for vinted.de — a JSON catalog API instead of an HTML result page.

Three things make this parser different from the HTML ones:

* **Session cookie.** ``/api/v2/catalog/items`` only answers requests that carry
  an anonymous session cookie, and that cookie is minted by a plain request to
  the HTML site. :meth:`BaseParser.fetch` opens a fresh client per call and can
  therefore never carry one, so this module keeps its own private fetch path
  that does the bootstrap request and the API request through ONE client.
* **JSON headers.** The base ``Accept`` header asks for HTML; the API answers
  that with an error page rather than data.
* **Unverified schema.** Every field name below is a hypothesis taken from the
  public API shape — none of it has been checked against a live response. The
  extraction is therefore defensive throughout: a missing or differently typed
  key costs a single listing, never the run.

Because of the last point the class is registered only when
``settings.vinted_enabled`` is true (see the bottom of this module).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config.clock import local_now
from app.config.settings import settings
from app.database.models.enums import Condition, SiteName
from app.parsers.base import BaseParser
from app.parsers.registry import register_parser
from app.parsers.schemas import ParsedListing, SearchQuery

BASE_URL = "https://www.vinted.de"
API_URL = f"{BASE_URL}/api/v2/catalog/items"
#: Any request to the HTML site answers with the Set-Cookie the API demands.
BOOTSTRAP_URL = f"{BASE_URL}/"

_JSON_ACCEPT = "application/json, text/plain, */*"
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_CURRENCY = "EUR"

#: How long a minted anonymous session is assumed to be good for. Re-minting
#: early costs one extra request, using a dead one costs a 401 plus a retry —
#: so this is deliberately far below the token's real lifetime.
_SESSION_TTL_SECONDS = 15 * 60
#: Upper bound the endpoint accepts for ``per_page``.
_MAX_PER_PAGE = 96

#: Vinted's German ``status`` label -> our condition enum. Anything unknown
#: stays ``ANY``: a relabelled status must never hide a listing.
STATUS_CONDITIONS: dict[str, Condition] = {
    "neu mit etikett": Condition.NEW,
    "neu mit preisschild": Condition.NEW,
    "neu ohne etikett": Condition.LIKE_NEW,
    "neu ohne preisschild": Condition.LIKE_NEW,
    "sehr gut": Condition.LIKE_NEW,
    "gut": Condition.USED,
    "zufriedenstellend": Condition.USED,
}

#: Keys a price object has carried; the amount itself uses a DOT decimal.
_PRICE_KEYS = ("amount", "value", "price")
#: A bare amount, nothing else. Parsing anything looser risks reading the
#: German "12,50" as 1250 — see :meth:`VintedParser._coerce_price`.
_AMOUNT_RE = re.compile(r"-?\d+(?:\.\d+)?")
#: Timestamps before this are not real offers, they are decoding accidents.
_EARLIEST_PLAUSIBLE_POST = datetime(2015, 1, 1)


class VintedParser(BaseParser):
    """Extracts offers from the vinted.de catalog API."""

    site = SiteName.VINTED
    label = "Vinted"
    requires_browser = False

    def __init__(self) -> None:
        super().__init__()
        # Parser instances are process-wide singletons while the worker runs
        # every task in a fresh event loop (base.py:55-72). Only plain data may
        # live on self: an httpx client or any asyncio primitive cached here
        # would blow up on the second task with "bound to a different event
        # loop". A cookie dict and an expiry float survive that.
        self._session_cookies: dict[str, str] = {}
        self._session_expires_at: float = 0.0
        self._unsupported_logged: bool = False

    # --- HTTP ---------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        """JSON headers for the API, on top of the base rotation."""
        headers = super()._headers()
        headers["Accept"] = _JSON_ACCEPT
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = f"{BASE_URL}/catalog"
        return headers

    def _cached_cookies(self) -> dict[str, str] | None:
        if self._session_cookies and time.monotonic() < self._session_expires_at:
            return dict(self._session_cookies)
        return None

    def _remember_cookies(self, cookies: Mapping[str, str]) -> None:
        # Flatten httpx's cookie jar into plain strings before it outlives the
        # client it belongs to.
        self._session_cookies = {str(k): str(v) for k, v in cookies.items()}
        self._session_expires_at = time.monotonic() + _SESSION_TTL_SECONDS

    def _forget_cookies(self) -> None:
        self._session_cookies = {}
        self._session_expires_at = 0.0

    def _note_block(self, status_code: int) -> None:
        """Mirror ``base.fetch``: a hard refusal is a block, not a parse bug."""
        if status_code in (403, 429, 503):
            self.mark_suspected_block()
            logger.warning(
                "[vinted] HTTP {} — treating as block signal", status_code
            )

    async def _ensure_session(
        self, client: httpx.AsyncClient, *, force: bool = False
    ) -> None:
        """Make sure ``client`` carries a session cookie for the API call."""
        if not force:
            cached = self._cached_cookies()
            if cached is not None:
                client.cookies.update(cached)
                return
        client.cookies.clear()
        try:
            resp = await client.get(BOOTSTRAP_URL, headers={"Accept": _HTML_ACCEPT})
        except httpx.HTTPError as exc:
            # Let the API call decide the outcome; it produces the better error.
            logger.warning("[vinted] session bootstrap failed: {}", exc)
            return
        self._note_block(resp.status_code)
        self._remember_cookies(client.cookies)

    @retry(
        stop=stop_after_attempt(max(1, settings.scraper_max_retries)),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception(BaseParser._is_retryable),
        reraise=True,
    )
    async def _fetch_json(self, params: dict[str, str | int]) -> object:
        """GET the catalog endpoint through one cookie-carrying client.

        Politeness stays the shared one — ``_throttle`` still coordinates the
        per-site delay through Redis, so this private path does not hand Vinted
        a second request budget next to the other parsers.
        """
        await self._throttle()
        async with httpx.AsyncClient(
            # One header set for both requests below: a session minted under
            # user agent A and then used under B is the exact mismatch bot
            # detection looks for.
            headers=self._headers(),
            timeout=settings.scraper_request_timeout,
            follow_redirects=True,
            proxy=self._random_proxy(),
        ) as client:
            await self._ensure_session(client)
            resp = await client.get(API_URL, params=params)
            if resp.status_code == 401:
                # Routine, not a block: the anonymous token expires on its own
                # schedule and the only cure is a fresh one.
                logger.debug("[vinted] 401 — re-minting the anonymous session")
                self._forget_cookies()
                await self._ensure_session(client, force=True)
                resp = await client.get(API_URL, params=params)
                if resp.status_code == 401:
                    self.mark_suspected_block()
                    logger.warning(
                        "[vinted] still HTTP 401 after a fresh session — blocked"
                    )
            self._note_block(resp.status_code)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                # HTML where JSON was promised is an interstitial, not data.
                self.mark_suspected_block()
                logger.warning("[vinted] catalog API answered with a non-JSON body")
                return None

    # --- Main entrypoint ----------------------------------------------------
    async def search(self, query: SearchQuery) -> list[ParsedListing]:
        self._log_unsupported_filters(query)
        params = self._build_params(query)
        logger.debug("[vinted] GET {} {}", API_URL, params)
        payload = await self._fetch_json(params)
        return self._parse_payload(payload, query)

    def _build_params(self, query: SearchQuery) -> dict[str, str | int]:
        """Build the catalog query string.

        ``order=newest_first`` is not cosmetic: a hunter polling every minute
        only ever sees the first page, and the default relevance sort keeps
        week-old items there while new offers never surface.
        """
        params: dict[str, str | int] = {
            "search_text": query.keywords.strip(),
            "page": 1,
            "per_page": min(max(query.max_results, 1), _MAX_PER_PAGE),
            "order": "newest_first",
            "currency": _CURRENCY,
        }
        # Dot decimals: the API speaks machine numbers, not German prices.
        if query.min_price is not None:
            params["price_from"] = f"{query.min_price:.2f}"
        if query.max_price is not None:
            params["price_to"] = f"{query.max_price:.2f}"
        return params

    def _log_unsupported_filters(self, query: SearchQuery) -> None:
        """Say once what this parser structurally cannot do.

        The catalog API has no radius search and its categories do not map onto
        our slugs, so those parts of a rule are ignored here. Staying silent
        would make the results look like a broken filter; one line per process
        explains them without flooding the log on every run.
        """
        if self._unsupported_logged:
            return
        ignored = []
        if query.location or query.zip_code or query.max_distance_km:
            ignored.append("location/zip/radius (the catalog API has no geo search)")
        if query.category:
            ignored.append("category (no mapping to Vinted's own catalog ids)")
        if not ignored:
            return
        self._unsupported_logged = True
        logger.info("[vinted] ignoring rule filters: {}", "; ".join(ignored))

    # --- Payload extraction (pure: no I/O, drivable from a fixture) ---------
    def _parse_payload(self, payload: object, query: SearchQuery) -> list[ParsedListing]:
        """Turn an already-decoded catalog response into listings."""
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            # A body without an items ARRAY is never an honest empty result: it
            # is an error envelope, an interstitial or a changed schema. An
            # empty array below, by contrast, simply means nothing matched.
            self.mark_suspected_block()
            logger.warning("[vinted] response has no items array — block or schema change")
            return []

        results: list[ParsedListing] = []
        for raw in items:
            try:
                item = self._parse_item(raw)
            except Exception as exc:  # noqa: BLE001 - one bad item, not the run
                logger.debug("[vinted] skipped an item: {}", exc)
                continue
            if item is None:
                continue
            if not query.matches_text(item.title, item.description):
                continue
            # Vinted reports a structured condition, so the filter the user
            # paid for can be honoured exactly here. Unknown stays unfiltered.
            if (
                query.condition is not Condition.ANY
                and item.condition is not Condition.ANY
                and item.condition is not query.condition
            ):
                continue
            if item.price is not None:
                if query.max_price is not None and item.price > query.max_price:
                    continue
                if query.min_price is not None and item.price < query.min_price:
                    continue
            # query.exclude_auctions is deliberately NOT applied: Vinted sells
            # at fixed prices only, so treating the flag as a filter would empty
            # the result for every rule that happens to have it switched on.
            results.append(item)
            if len(results) >= query.max_results:
                break
        return results

    @classmethod
    def _parse_item(cls, raw: object) -> ParsedListing | None:
        if not isinstance(raw, dict):
            return None
        external_id = cls._first_str(raw, "id", "item_id")
        if not external_id:
            # The id is the whole identity of an offer: fingerprint, price-drop
            # matching and cross-rule dedup all hang off it. An item without one
            # would be re-notified on every single run.
            return None

        brand = cls._first_str(raw, "brand_title", "brand") or cls._nested_str(
            raw, "brand", "title"
        )
        size = cls._first_str(raw, "size_title", "size") or cls._nested_str(
            raw, "size", "title"
        )
        status = cls._first_str(raw, "status", "condition")
        # Brand and size go into the DESCRIPTION, never into the title: the
        # title feeds the repost hash (widening it breaks repost detection),
        # while the relevance check reads title AND description, so extra text
        # here can only help a query match.
        description = " · ".join(p for p in (brand, size, status) if p) or None

        price_field = raw.get("price")
        price = cls._coerce_price(price_field)
        if price is None:
            # Older payloads only carried the buyer-side total.
            price = cls._coerce_price(raw.get("total_item_price"))

        return ParsedListing(
            site=SiteName.VINTED,
            external_id=external_id,
            title=cls._first_str(raw, "title", "name") or "(kein Titel)",
            url=cls._item_url(raw, external_id),
            price=price,
            currency=cls._currency(price_field),
            # Vinted quotes shipping per carrier at checkout, so the catalog
            # cannot tell us a price — which is also why query.shipping_available
            # is left unfiltered. None = unknown, 0.0 would be a lie.
            shipping_cost=None,
            image_url=cls._image_url(raw),
            description=description,
            location=cls._nested_str(raw, "user", "city") or cls._first_str(raw, "city"),
            condition=STATUS_CONDITIONS.get((status or "").lower(), Condition.ANY),
            seller_name=cls._nested_str(raw, "user", "login"),
            seller_rating=cls._seller_rating(raw),
            is_auction=False,  # Vinted has no auctions at all.
            posted_at=cls._posted_at(raw),
        )

    # --- Small helpers ------------------------------------------------------
    @staticmethod
    def _first_str(data: dict, *keys: str) -> str | None:
        """First present key whose value is a non-empty scalar."""
        for key in keys:
            value = data.get(key)
            if isinstance(value, bool) or not isinstance(value, str | int | float):
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @classmethod
    def _nested_str(cls, data: dict, *path: str) -> str | None:
        """Walk ``path`` through nested dicts, tolerating every gap."""
        current: object = data
        for key in path[:-1]:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        if not isinstance(current, dict):
            return None
        return cls._first_str(current, path[-1])

    @classmethod
    def _coerce_price(cls, raw: object) -> float | None:
        """Read the amount out of either shape the API has served.

        Both ``{"amount": "12.50", "currency_code": "EUR"}`` and a bare
        ``"12.50"`` must work. The decimal separator is a DOT — the German
        comma helpers the other parsers use would read 12.50 as 1250, i.e.
        turn a bargain into a price-drop alert that never fires.
        """
        if isinstance(raw, dict):
            raw = next((raw[key] for key in _PRICE_KEYS if key in raw), None)
        if isinstance(raw, bool):  # bool is an int subclass; a flag is no price
            return None
        if isinstance(raw, int | float):
            return float(raw)
        if not isinstance(raw, str):
            return None
        text = raw.strip().replace("\xa0", "").replace(" ", "").strip("€").strip()
        # fullmatch, not search: a grouped "1,234.50" must fail loudly (price
        # None) rather than silently become 1.
        return float(text) if _AMOUNT_RE.fullmatch(text) else None

    @classmethod
    def _currency(cls, price_field: object) -> str:
        if isinstance(price_field, dict):
            code = cls._first_str(price_field, "currency_code", "currency")
            if code:
                return code[:3].upper()
        return _CURRENCY

    @classmethod
    def _item_url(cls, raw: dict, external_id: str) -> str:
        """Absolute item URL; the API has served both absolute and relative."""
        candidate = cls._first_str(raw, "url", "path")
        if candidate:
            absolute = urljoin(BOOTSTRAP_URL, candidate)
            if absolute.startswith("http"):
                return absolute
        return f"{BASE_URL}/items/{quote(external_id, safe='')}"

    @classmethod
    def _image_url(cls, raw: dict) -> str | None:
        photo = raw.get("photo")
        if not isinstance(photo, dict):
            photos = raw.get("photos")
            photo = photos[0] if isinstance(photos, list) and photos else None
        if not isinstance(photo, dict):
            return None
        for key in ("url", "full_size_url", "thumbnail_url"):
            value = photo.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        return None

    @classmethod
    def _seller_rating(cls, raw: dict) -> float | None:
        """Map Vinted's 0..1 reputation onto the 0..5 star scale.

        Every other parser stores a star count, so a raw 0.87 would read as a
        catastrophic seller right next to an eBay 4.9.
        """
        user = raw.get("user")
        value = user.get("feedback_reputation") if isinstance(user, dict) else None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        if 0.0 <= value <= 1.0:
            return round(float(value) * 5.0, 2)
        if 1.0 < value <= 5.0:  # already a star value
            return round(float(value), 2)
        return None

    @classmethod
    def _posted_at(cls, raw: dict) -> datetime | None:
        """Creation time, if the item carries an explicit one.

        Only item-level date fields are read. The photo timestamps in the same
        payload are image upload times and can be months older than the offer —
        which is also why ``SiteName.VINTED`` stays out of
        ``freshness.DATE_AWARE_SITES`` until this has been confirmed against a
        live response: a wrong timestamp there marks every item stale and the
        product delivers nothing.
        """
        value = raw.get("created_at_ts")
        if value is None:
            value = raw.get("created_at")
        parsed = cls._parse_timestamp(value)
        if parsed is None:
            return None
        if parsed < _EARLIEST_PLAUSIBLE_POST:
            return None
        if parsed > local_now() + timedelta(days=1):
            return None
        return parsed

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        """Epoch seconds, epoch milliseconds or ISO 8601 -> naive local time.

        Naive local, because that is what every other parser produces and what
        ``freshness`` compares against (see ``app/config/clock.py``); a UTC
        value would silently shift every age by the German offset.
        """
        if isinstance(value, bool):
            return None
        try:
            if isinstance(value, int | float):
                seconds = float(value)
                if seconds > 1e11:  # milliseconds
                    seconds /= 1000.0
                return VintedParser._local_naive(seconds)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                if text.replace(".", "", 1).isdigit():
                    return VintedParser._parse_timestamp(float(text))
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return parsed
                return VintedParser._local_naive(parsed.timestamp())
        except (ValueError, OverflowError, OSError):
            return None
        return None

    @staticmethod
    def _local_naive(epoch_seconds: float) -> datetime:
        try:
            from zoneinfo import ZoneInfo

            return datetime.fromtimestamp(
                epoch_seconds, ZoneInfo(settings.tz)
            ).replace(tzinfo=None)
        except Exception:  # noqa: BLE001 - no tz database available
            return datetime.fromtimestamp(epoch_seconds)


# Flagged registration, deliberately not a decorator: a SearchRule stores
# ``sites=[]`` by default and the registry resolves that to EVERY registered
# parser. An unconditional registration would therefore put this parser — whose
# field names have never seen a live response — in front of every user on the
# next deploy. Turn VINTED_ENABLED on only after verifying the payload shape.
if settings.vinted_enabled:
    register_parser(VintedParser)
    logger.info("[vinted] parser registered (VINTED_ENABLED=true)")
