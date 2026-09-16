"""Tests for the Vinted JSON catalog parser.

Vinted is a JSON API, so the fixture below is a decoded payload rather than
HTML. Every field name in it is a HYPOTHESIS about the live response — these
tests pin the parser's behaviour (defensive extraction, dot decimals, block
signalling, session handling), not Vinted's schema.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.database.models.enums import Condition, SiteName
from app.parsers import registry
from app.parsers.schemas import SearchQuery
from app.parsers.sites import vinted
from app.parsers.sites.vinted import VintedParser

#: Two items in the two price/photo shapes the API has served, plus one
#: item without an id (which has no identity and must be dropped).
SAMPLE_PAYLOAD: dict = {
    "items": [
        {
            "id": 4711123,
            "title": "Nike Air Max 90 Sneaker",
            "url": "https://www.vinted.de/items/4711123-nike-air-max-90",
            "price": {"amount": "12.50", "currency_code": "EUR"},
            "total_item_price": {"amount": "14.20", "currency_code": "EUR"},
            "brand_title": "Nike",
            "size_title": "42",
            "status": "Sehr gut",
            "photo": {"url": "https://images.vinted.net/t/air-max.jpeg"},
            "user": {
                "login": "sneakerfan",
                "city": "Köln",
                "feedback_reputation": 0.94,
            },
            "created_at_ts": 1757930400,  # 2025-09-15, 10:00 UTC
        },
        {
            # Older shape: bare string price, relative path, nested brand/size,
            # photos list instead of a photo object, no seller reputation.
            "id": "4711124",
            "title": "Nike Air Max 90 Damen",
            "path": "/items/4711124-nike-air-max-90-damen",
            "price": "8.00",
            "brand": {"title": "Nike"},
            "size": {"title": "38"},
            "status": "Gut",
            "photos": [
                {"full_size_url": "https://images.vinted.net/t/air-max-2.jpeg"}
            ],
            "user": {"login": "vintage_shop"},
        },
        {
            "title": "Nike Air Max 90 ohne ID",
            "price": {"amount": "5.00"},
        },
    ],
    "pagination": {"current_page": 1, "total_entries": 2},
}


@pytest.fixture()
def parser() -> VintedParser:
    return VintedParser()


@pytest.fixture()
def no_throttle(monkeypatch):
    """No Redis round trip and no real sleeping during the HTTP tests."""
    monkeypatch.setattr(vinted.settings, "scraper_min_delay_seconds", 0.0)


# --- Payload extraction ----------------------------------------------------
def test_parse_payload_maps_core_fields(parser):
    items = parser._parse_payload(SAMPLE_PAYLOAD, SearchQuery(keywords="nike air max"))

    assert len(items) == 2  # the id-less entry is gone
    first = items[0]
    assert first.site is SiteName.VINTED
    assert first.external_id == "4711123"
    assert first.title == "Nike Air Max 90 Sneaker"
    assert str(first.url) == "https://www.vinted.de/items/4711123-nike-air-max-90"
    assert first.price == 12.50
    assert first.currency == "EUR"
    assert str(first.image_url) == "https://images.vinted.net/t/air-max.jpeg"
    assert first.location == "Köln"
    assert first.seller_name == "sneakerfan"
    assert first.condition is Condition.LIKE_NEW
    assert first.is_auction is False
    # Shipping is quoted at checkout, so "unknown" — never a fake 0.
    assert first.shipping_cost is None
    assert parser._suspect_block is False


def test_alternative_shapes_are_accepted(parser):
    second = parser._parse_payload(SAMPLE_PAYLOAD, SearchQuery(keywords="nike"))[1]

    assert second.external_id == "4711124"
    assert second.price == 8.00
    # Relative path resolved against the site root.
    assert str(second.url) == (
        "https://www.vinted.de/items/4711124-nike-air-max-90-damen"
    )
    assert str(second.image_url) == "https://images.vinted.net/t/air-max-2.jpeg"
    assert "Nike" in (second.description or "")
    assert "38" in (second.description or "")
    assert second.seller_rating is None


def test_price_uses_a_dot_decimal_not_a_german_comma(parser):
    # The bug this guards: reusing the comma helpers turns 12.50 into 1250.
    assert parser._coerce_price({"amount": "12.50", "currency_code": "EUR"}) == 12.50
    assert parser._coerce_price("8.00") == 8.00
    assert parser._coerce_price("12.50 €") == 12.50
    assert parser._coerce_price(7) == 7.0
    assert parser._coerce_price(None) is None
    assert parser._coerce_price({}) is None
    assert parser._coerce_price(True) is None
    # An unknown grouped format must yield "no price", never a wrong one.
    assert parser._coerce_price("1,234.50") is None


def test_brand_and_size_go_into_the_description_not_the_title(parser):
    first = parser._parse_payload(SAMPLE_PAYLOAD, SearchQuery(keywords="nike"))[0]

    assert "Nike" not in first.title.replace("Nike Air Max 90 Sneaker", "")
    assert first.title == "Nike Air Max 90 Sneaker"  # untouched -> repost hash stable
    assert first.description is not None
    assert "Nike" in first.description
    assert "42" in first.description
    assert "Sehr gut" in first.description


def test_seller_rating_is_mapped_onto_the_star_scale(parser):
    first = parser._parse_payload(SAMPLE_PAYLOAD, SearchQuery(keywords="nike"))[0]
    assert first.seller_rating == pytest.approx(4.7)


def test_posted_at_is_read_from_the_item_timestamp(parser):
    first = parser._parse_payload(SAMPLE_PAYLOAD, SearchQuery(keywords="nike"))[0]
    assert first.posted_at is not None
    assert (first.posted_at.year, first.posted_at.month, first.posted_at.day) == (
        2025,
        9,
        15,
    )
    # The second item has no timestamp at all and must not invent one.
    second = parser._parse_payload(SAMPLE_PAYLOAD, SearchQuery(keywords="nike"))[1]
    assert second.posted_at is None


def test_implausible_timestamps_are_dropped(parser):
    payload = {"items": [{"id": "1", "title": "x", "created_at_ts": 0}]}
    assert parser._parse_payload(payload, SearchQuery(keywords="x"))[0].posted_at is None

    far_future = {"items": [{"id": "1", "title": "x", "created_at_ts": 99_999_999_999}]}
    item = parser._parse_payload(far_future, SearchQuery(keywords="x"))[0]
    assert item.posted_at is None


def test_item_without_external_id_is_skipped(parser):
    payload = {"items": [{"title": "Kein Ausweis", "price": "5.00"}]}
    assert parser._parse_payload(payload, SearchQuery(keywords="kein")) == []
    # Skipping items is not a block signal.
    assert parser._suspect_block is False


def test_malformed_item_does_not_kill_the_batch(parser):
    payload = {"items": ["nonsense", {"id": "9", "title": "Nike Shirt", "price": "3.00"}]}
    items = parser._parse_payload(payload, SearchQuery(keywords="nike"))
    assert [i.external_id for i in items] == ["9"]


# --- Block signalling ------------------------------------------------------
def test_empty_items_list_is_an_honest_empty_result(parser):
    items = parser._parse_payload({"items": [], "pagination": {}}, SearchQuery(keywords="x"))
    assert items == []
    assert parser._suspect_block is False


def test_missing_items_key_is_a_block_signal(parser):
    assert parser._parse_payload({"pagination": {}}, SearchQuery(keywords="x")) == []
    assert parser._suspect_block is True


def test_non_dict_body_is_a_block_signal(parser):
    assert parser._parse_payload("<html>captcha</html>", SearchQuery(keywords="x")) == []
    assert parser._suspect_block is True


def test_items_not_a_list_is_a_block_signal(parser):
    assert parser._parse_payload({"items": {"0": {}}}, SearchQuery(keywords="x")) == []
    assert parser._suspect_block is True


def test_refusal_status_codes_are_marked(parser):
    for status in (403, 429, 503):
        fresh = VintedParser()
        fresh._note_block(status)
        assert fresh._suspect_block is True
    parser._note_block(200)
    assert parser._suspect_block is False


# --- Query handling --------------------------------------------------------
def test_exclude_auctions_is_a_no_op(parser):
    query = SearchQuery(keywords="nike air max", exclude_auctions=True)
    # Vinted has no auctions; the flag must not empty the result.
    assert len(parser._parse_payload(SAMPLE_PAYLOAD, query)) == 2


def test_exclude_keywords_and_price_bounds_filter(parser):
    query = SearchQuery(keywords="nike", exclude_keywords=["damen"])
    assert [i.external_id for i in parser._parse_payload(SAMPLE_PAYLOAD, query)] == [
        "4711123"
    ]

    cheap = SearchQuery(keywords="nike", max_price=10.0)
    assert [i.external_id for i in parser._parse_payload(SAMPLE_PAYLOAD, cheap)] == [
        "4711124"
    ]

    pricey = SearchQuery(keywords="nike", min_price=10.0)
    assert [i.external_id for i in parser._parse_payload(SAMPLE_PAYLOAD, pricey)] == [
        "4711123"
    ]


def test_max_results_caps_the_batch(parser):
    query = SearchQuery(keywords="nike", max_results=1)
    assert len(parser._parse_payload(SAMPLE_PAYLOAD, query)) == 1


def test_build_params_sorts_newest_first(parser):
    params = parser._build_params(
        SearchQuery(keywords=" nike air max ", min_price=5, max_price=40, max_results=10)
    )
    assert params["order"] == "newest_first"  # a minute-poller needs the new ones
    assert params["search_text"] == "nike air max"
    assert params["price_from"] == "5.00"
    assert params["price_to"] == "40.00"
    assert params["per_page"] == 10


def test_build_params_caps_per_page(parser):
    params = parser._build_params(SearchQuery(keywords="nike", max_results=5000))
    assert params["per_page"] == vinted._MAX_PER_PAGE


def test_unsupported_geo_filters_are_logged_once(parser):
    query = SearchQuery(keywords="nike", zip_code="50667", max_distance_km=20)
    parser._log_unsupported_filters(query)
    assert parser._unsupported_logged is True
    parser._log_unsupported_filters(query)  # second call stays silent

    quiet = VintedParser()
    quiet._log_unsupported_filters(SearchQuery(keywords="nike"))
    assert quiet._unsupported_logged is False


# --- Headers / session -----------------------------------------------------
def test_headers_ask_for_json_and_keep_the_rotating_user_agent(parser):
    headers = parser._headers()
    assert headers["Accept"].startswith("application/json")
    assert headers["User-Agent"]
    assert headers["Accept-Language"].startswith("de-DE")


class _ScriptedClient:
    """Drop-in for ``httpx.AsyncClient``: replays scripted API responses.

    Any non-API URL counts as the cookie bootstrap and mints a session cookie,
    which is exactly the behaviour the parser depends on.
    """

    def __init__(self, api_responses: list[httpx.Response], urls: list[str]) -> None:
        self._api_responses = api_responses
        self._urls = urls
        self.cookies: dict[str, str] = {}

    async def __aenter__(self) -> _ScriptedClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url, params=None, headers=None) -> httpx.Response:
        self._urls.append(url)
        if url == vinted.API_URL:
            return self._api_responses.pop(0)
        self.cookies["_vinted_fr_session"] = f"token-{len(self._urls)}"
        return httpx.Response(200, request=httpx.Request("GET", url), text="<html>")


def _install_client(monkeypatch, api_responses: list[httpx.Response]) -> list[str]:
    urls: list[str] = []
    monkeypatch.setattr(
        vinted.httpx,
        "AsyncClient",
        lambda **kwargs: _ScriptedClient(api_responses, urls),
    )
    return urls


def _api_response(status: int, payload: dict | None = None) -> httpx.Response:
    request = httpx.Request("GET", vinted.API_URL)
    return httpx.Response(status, request=request, json=payload or {})


def test_fetch_json_bootstraps_a_session_then_calls_the_api(
    parser, monkeypatch, no_throttle
):
    urls = _install_client(monkeypatch, [_api_response(200, SAMPLE_PAYLOAD)])

    payload = asyncio.run(parser._fetch_json({"search_text": "nike"}))

    assert payload["pagination"]["current_page"] == 1
    assert urls == [vinted.BOOTSTRAP_URL, vinted.API_URL]
    # Only plain data may be cached on the instance.
    assert parser._session_cookies == {"_vinted_fr_session": "token-1"}
    assert isinstance(parser._session_expires_at, float)


def test_cached_session_is_reused_across_event_loops(parser, monkeypatch, no_throttle):
    """The worker runs every task in a fresh loop on the same parser instance."""
    urls = _install_client(monkeypatch, [_api_response(200, SAMPLE_PAYLOAD)])
    asyncio.run(parser._fetch_json({"search_text": "nike"}))

    second_urls = _install_client(monkeypatch, [_api_response(200, SAMPLE_PAYLOAD)])
    asyncio.run(parser._fetch_json({"search_text": "nike"}))

    assert urls == [vinted.BOOTSTRAP_URL, vinted.API_URL]
    assert second_urls == [vinted.API_URL]  # cookie still valid -> no bootstrap


def test_expired_session_is_re_minted_on_401(parser, monkeypatch, no_throttle):
    urls = _install_client(
        monkeypatch,
        [_api_response(401, {"message": "Token expired"}),
         _api_response(200, SAMPLE_PAYLOAD)],
    )

    payload = asyncio.run(parser._fetch_json({"search_text": "nike"}))

    assert payload["items"]
    assert urls == [
        vinted.BOOTSTRAP_URL,
        vinted.API_URL,
        vinted.BOOTSTRAP_URL,
        vinted.API_URL,
    ]
    # A routine token expiry is not a block.
    assert parser._suspect_block is False


def test_persistent_401_is_treated_as_a_block(parser, monkeypatch, no_throttle):
    _install_client(
        monkeypatch, [_api_response(401, {}), _api_response(401, {})]
    )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(parser._fetch_json({"search_text": "nike"}))
    assert parser._suspect_block is True


def test_non_json_body_is_a_block(parser, monkeypatch, no_throttle):
    request = httpx.Request("GET", vinted.API_URL)
    _install_client(
        monkeypatch, [httpx.Response(200, request=request, text="<html>captcha</html>")]
    )

    assert asyncio.run(parser._fetch_json({"search_text": "nike"})) is None
    assert parser._suspect_block is True


def test_search_returns_parsed_listings(parser, monkeypatch, no_throttle):
    _install_client(monkeypatch, [_api_response(200, SAMPLE_PAYLOAD)])

    items = asyncio.run(parser.search(SearchQuery(keywords="nike air max")))
    assert [i.external_id for i in items] == ["4711123", "4711124"]


# --- Registration ----------------------------------------------------------
def test_parser_registration_follows_the_feature_flag():
    registered = SiteName.VINTED in registry.available_sites
    assert registered is vinted.settings.vinted_enabled
