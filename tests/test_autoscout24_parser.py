"""AutoScout24 parser: taxonomy resolution, card parsing and the free-text trap.

The trap is the reason this parser exists in the shape it does: AutoScout24
accepts ``q=`` and ignores it, answering every unrecognised search with the
whole German car inventory. Most of these tests pin down that a rule which
names no make never reaches the site at all.
"""

from __future__ import annotations

import asyncio
import json

from app.database.models.enums import Condition, SiteName
from app.parsers.schemas import SearchQuery
from app.parsers.sites.autoscout24 import (
    AutoScout24Parser,
    build_search_url,
    close_variant_spacing,
    condition_matches,
    extract_payload,
    mentions,
    parse_listing,
    parse_listings,
    read_makes,
    read_model_groups,
    resolve_make,
    resolve_model_group,
)


def _page(page_props: dict) -> str:
    """A result page the way AutoScout24 serves it: JSON inside a script tag."""
    payload = json.dumps({"props": {"pageProps": page_props}}, ensure_ascii=False)
    return (
        "<html><body><div id=\"__next\">…</div>"
        f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'
        "</body></html>"
    )


#: Every result page carries the make list; the parser reads it from there
#: rather than from a hard-coded table that would rot without anyone noticing.
MAKES = {
    "taxonomy": {
        "makesSorted": [
            {"label": "AC", "value": 14979},
            {"label": "Alfa Romeo", "value": 6},
            {"label": "BMW", "value": 13},
            {"label": "Citroën", "value": 21},
            {"label": "Mercedes-Benz", "value": 47},
            {"label": "Tesla", "value": 51520},
            {"label": "Volkswagen", "value": 74},
        ]
    }
}

#: A make's model groups only appear once that make is selected.
GROUPS = {
    13: {"taxonomy": {"modelGroups": {"13": [
        {"label": "1er", "value": 2},
        {"label": "3er", "value": 4},
        {"label": "5er", "value": 6},
    ]}}},
    51520: {"taxonomy": {"modelGroups": {"51520": [
        {"label": "Model 3", "value": 201429},
        {"label": "Model Y", "value": 201430},
    ]}}},
    74: {"taxonomy": {"modelGroups": {"74": [
        {"label": "Golf", "value": 100},
        {"label": "Golf Plus", "value": 101},
    ]}}},
}

#: One real card, trimmed to the fields the parser reads.
CARD = {
    "id": "37b8819c-d27a-44d7-a241-036aa6fef377",
    "url": "/angebote/tesla-model-3-long-range-awd-37b8819c-d27a-44d7-a241-036aa6fef377",
    "images": [
        "https://prod.pictures.autoscout24.net/listing-images/a.jpg",
        "https://prod.pictures.autoscout24.net/listing-images/b.jpg",
    ],
    "location": {"city": "Emsbüren", "countryCode": "DE", "zip": "48488"},
    "price": {"priceFormatted": "€ 22.750", "priceRaw": 22750},
    "superDeal": {"isEligible": True, "oldPriceFormatted": "€ 23.750,-"},
    "seller": {"companyName": "Exclusive Cars GmbH", "type": "Dealer"},
    "tracking": {
        "firstRegistration": "12-2020",
        "mileage": "168999",
        "price": "22750",
    },
    "vehicle": {
        "make": "Tesla",
        "model": "Model 3",
        "modelGroup": "Model 3",
        "modelVersionInput": "MODEL 3 LONG RANGE AWD | AIR LIFT SYSTEM |",
        "offerType": "U",
        "isCurrentlyDamaged": False,
        "subtitle": "HU/AU neu, Sitzheizung, Garantie",
        "mileageInKm": "168.999 km",
    },
}


def _card(**overrides):
    """A copy of the sample card with nested dicts replaced, not merged."""
    card = json.loads(json.dumps(CARD))
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(card.get(key), dict):
            card[key].update(value)
        else:
            card[key] = value
    return card


# --- Payload ---------------------------------------------------------------------
def test_payload_is_read_out_of_the_page_script():
    props = extract_payload(_page({"listings": [CARD], "numberOfResults": 277}))
    assert props is not None
    assert props["numberOfResults"] == 277


def test_a_page_without_the_payload_is_not_a_payload():
    assert extract_payload("<html><body>Zugriff verweigert</body></html>") is None
    assert extract_payload(
        '<script id="__NEXT_DATA__" type="application/json">{nope</script>'
    ) is None


# --- Card parsing ----------------------------------------------------------------
def test_card_carries_the_structured_car_fields():
    item = parse_listing(CARD)
    assert item is not None
    assert item.site is SiteName.AUTOSCOUT24
    assert item.external_id == "37b8819c-d27a-44d7-a241-036aa6fef377"
    assert str(item.url).startswith("https://www.autoscout24.de/angebote/")
    assert item.price == 22750.0
    assert item.mileage_km == 168999
    assert item.registration_year == 2020
    assert item.location == "48488 Emsbüren"
    assert item.seller_name == "Exclusive Cars GmbH"
    assert item.condition is Condition.USED
    assert str(item.image_url).endswith("/a.jpg")
    # Cars are collected and AutoScout24 runs no auctions — a rule filtering on
    # either must not be emptied by a value this site cannot report.
    assert item.shipping_available is None
    assert item.is_auction is False
    # The site does not publish when the ad went online; that is unknown, and
    # unknown is None rather than "now".
    assert item.posted_at is None


def test_title_does_not_repeat_the_model():
    # The seller's version line already contains "MODEL 3" — printing model and
    # version both reads as "Tesla Model 3 MODEL 3 LONG RANGE AWD".
    assert parse_listing(CARD).title == "Tesla MODEL 3 LONG RANGE AWD AIR LIFT SYSTEM"


def test_title_keeps_the_model_when_the_version_does_not_name_it():
    item = parse_listing(_card(vehicle={"modelVersionInput": "Long Range AWD"}))
    assert item.title == "Tesla Model 3 Long Range AWD"


def test_reduced_price_is_kept_only_when_it_really_is_a_reduction():
    assert parse_listing(CARD).original_price == 23750.0
    # A "previous" price at or below the asking price is noise, not a discount.
    same = parse_listing(_card(superDeal={"oldPriceFormatted": "€ 22.750,-"}))
    assert same.original_price is None


def test_mileage_falls_back_to_the_printed_kilometres():
    item = parse_listing(_card(tracking={"mileage": None}))
    assert item.mileage_km == 168999  # from "168.999 km"


def test_cards_without_an_id_or_url_are_skipped_not_crashed():
    props = {"listings": [CARD, {"id": "x"}, {"url": "/y"}, "nonsense"]}
    assert len(parse_listings(props)) == 1


# --- Condition -------------------------------------------------------------------
def test_damage_beats_the_offer_type():
    item = parse_listing(_card(vehicle={"isCurrentlyDamaged": True, "offerType": "N"}))
    assert item.condition is Condition.DEFECTIVE


def test_unknown_damage_is_not_damage():
    # The flag is missing on some cards. Reading that as "defective" would drop
    # every such car out of a "gebraucht" rule.
    item = parse_listing(_card(vehicle={"isCurrentlyDamaged": None}))
    assert item.condition is Condition.USED


def test_only_offer_type_n_is_a_new_car():
    assert parse_listing(_card(vehicle={"offerType": "N"})).condition is Condition.NEW
    for letter in ("U", "D", "J", "O", "A"):
        item = parse_listing(_card(vehicle={"offerType": letter}))
        assert item.condition is Condition.USED, letter


def test_condition_filter_matches_the_kleinanzeigen_semantics():
    assert condition_matches(Condition.ANY, Condition.DEFECTIVE) is True
    assert condition_matches(Condition.USED, Condition.USED) is True
    assert condition_matches(Condition.USED, Condition.NEW) is True
    assert condition_matches(Condition.USED, Condition.DEFECTIVE) is False
    assert condition_matches(Condition.NEW, Condition.USED) is False
    assert condition_matches(Condition.DEFECTIVE, Condition.DEFECTIVE) is True


# --- Taxonomy resolution ---------------------------------------------------------
def test_makes_and_groups_come_from_the_page_itself():
    makes = read_makes(MAKES)
    assert makes["bmw"] == 13
    assert makes["mercedes benz"] == 47
    # "Citroën" and "citroen" have to reach the same key.
    assert makes["citroen"] == 21
    assert read_model_groups(GROUPS[13], 13)["3er"] == 4


def test_the_make_must_stand_at_the_front():
    makes = read_makes(MAKES)
    assert resolve_make("Tesla Model 3", makes) == (51520, ["model", "3"])
    assert resolve_make("Mercedes-Benz C 200", makes)[0] == 47
    assert resolve_make("vw golf", makes) == (74, ["golf"])
    # "AC" is a real make. Matching it in the middle of a sentence would send a
    # console hunt to a car marketplace.
    assert resolve_make("PS5 AC Adapter", makes) is None
    assert resolve_make("iPhone 15 Pro", makes) is None
    assert resolve_make("", makes) is None


def test_the_longest_make_wins():
    # "Alfa" alone is an alias; "Alfa Romeo" is the real label and must not be
    # cut short, or the leftover "romeo" would be searched as a model.
    assert resolve_make("Alfa Romeo Giulia", read_makes(MAKES)) == (6, ["giulia"])


def test_model_group_resolution_consumes_the_tokens_it_used():
    tesla = read_model_groups(GROUPS[51520], 51520)
    # "model 3" named the group, so nothing is left to check against the text.
    assert resolve_model_group(["model", "3"], tesla) == (201429, [])
    vw = read_model_groups(GROUPS[74], 74)
    assert resolve_model_group(["golf", "plus"], vw) == (101, [])
    assert resolve_model_group(["golf", "gti"], vw) == (100, ["gti"])
    assert resolve_model_group(["passat"], vw) == (None, ["passat"])
    assert resolve_model_group([], vw) == (None, [])


def test_a_bmw_engine_variant_finds_its_series_and_stays_a_keyword():
    # People search for "320d", AutoScout24 groups by "3er". Without this the
    # rule would walk the newest 20 of 63.000 BMWs and match nothing.
    bmw = read_model_groups(GROUPS[13], 13)
    # The token is NOT consumed: "320d" says more than "3er", so it still has
    # to be found in the ad, or a 318i would pass as a 320d.
    assert resolve_model_group(["320d"], bmw) == (4, ["320d"])
    assert resolve_model_group(["520i"], bmw) == (6, ["520i"])
    # …and it may not invent a series for a make that numbers nothing.
    assert resolve_model_group(["320d"], read_model_groups(GROUPS[74], 74)) == (
        None,
        ["320d"],
    )


# --- Keyword matching against the dealer's spelling -------------------------------
def test_engine_variants_survive_the_dealers_spacing():
    # Dealers type "BMW 320 d", people search for "320d". This exact mismatch
    # threw away all 20 real 3er hits in the first live run of this parser.
    assert close_variant_spacing("BMW 320 d HiFi NAVI") == "bmw 320d hifi navi"
    assert mentions(["320d"], "BMW 320 d HiFi NAVI") is True
    assert mentions(["320d"], "BMW 318i Advantage") is False
    # Only a single letter behind a number is pulled in — words stay words.
    assert close_variant_spacing("BMW 320 3er") == "bmw 320 3er"
    assert mentions([], "anything at all") is True


# --- URL building ----------------------------------------------------------------
def test_url_carries_the_rules_own_filters():
    query = SearchQuery(
        keywords="tesla model 3",
        min_price=15000,
        max_price=25000,
        zip_code="67547",
        max_distance_km=100,
    )
    url = build_search_url(query, make_id=51520, group_id=201429)
    assert "cat=ma51520gr201429" in url
    assert "pricefrom=15000" in url and "priceto=25000" in url
    assert "zip=67547" in url and "zipr=100" in url
    assert "sort=age" in url  # "Neueste Angebote zuerst"
    assert "damaged_listing=exclude" in url
    assert "page=" not in url


def test_a_defect_hunt_asks_for_damaged_cars():
    query = SearchQuery(keywords="bmw 3er", condition=Condition.DEFECTIVE)
    assert "damaged_listing=only" in build_search_url(query, make_id=13, group_id=4)


def test_a_make_without_a_model_is_still_a_valid_search():
    url = build_search_url(SearchQuery(keywords="tesla"), make_id=51520, group_id=None)
    assert "cat=ma51520&" in url or url.endswith("cat=ma51520")


# --- End to end ------------------------------------------------------------------
class _StubbedParser(AutoScout24Parser):
    """The real parser with the network replaced by the fixtures above."""

    def __init__(self, result_pages: list[dict] | None = None) -> None:
        super().__init__()
        self.requested: list[str] = []
        self._result_pages = result_pages if result_pages is not None else [
            {"listings": [CARD]}
        ]

    async def fetch_text(self, url: str, params=None) -> str:  # noqa: ANN001
        self.requested.append(url)
        if "cat=ma" not in url:
            return _page(MAKES)
        make_id = int(url.split("cat=ma")[1].split("gr")[0].split("&")[0])
        if "sort=age" not in url:
            return _page(GROUPS.get(make_id, {"taxonomy": {"modelGroups": {}}}))
        page = int(url.split("page=")[1].split("&")[0]) if "page=" in url else 1
        index = page - 1
        if index >= len(self._result_pages):
            return _page({"listings": []})
        return _page(self._result_pages[index])


def test_a_search_naming_no_make_never_reaches_the_result_pages():
    parser = _StubbedParser()
    found = asyncio.run(parser.search(SearchQuery(keywords="iPhone 15 Pro")))
    assert found == []
    # The make list is fetched once (and then cached for hours); no search is
    # ever sent, because AutoScout24 would answer it with every car it has.
    assert len(parser.requested) == 1
    assert all("sort=age" not in url for url in parser.requested)
    assert parser._suspect_block is False  # not a failure, just not a car


def test_a_car_search_resolves_make_and_model_and_returns_the_card():
    parser = _StubbedParser()
    found = asyncio.run(parser.search(SearchQuery(keywords="Tesla Model 3")))
    assert [item.external_id for item in found] == [CARD["id"]]
    assert any("cat=ma51520gr201429" in url for url in parser.requested)


def test_the_taxonomy_is_fetched_once_not_once_per_search():
    parser = _StubbedParser()
    query = SearchQuery(keywords="Tesla Model 3")
    asyncio.run(parser.search(query))
    first = len(parser.requested)
    asyncio.run(parser.search(query))
    # Second run: one request for the result page, nothing for the taxonomy.
    assert len(parser.requested) - first == 1


def test_excluded_keywords_and_price_are_enforced_locally():
    cheap = _card(id="cheap", price={"priceRaw": 9000}, superDeal={})
    unwanted = _card(id="unwanted", vehicle={"subtitle": "Unfallwagen, Bastler"})
    parser = _StubbedParser([{"listings": [CARD, cheap, unwanted]}])
    query = SearchQuery(
        keywords="Tesla Model 3",
        min_price=10000,
        exclude_keywords=["unfall"],
        max_results=10,
    )
    found = asyncio.run(parser.search(query))
    assert [item.external_id for item in found] == [CARD["id"]]


def _bmw(listing_id: str, version: str) -> dict:
    return _card(
        id=listing_id,
        vehicle={
            "make": "BMW",
            "model": "3er",
            "modelGroup": "3er",
            "modelVersionInput": version,
            "subtitle": "",
        },
    )


def test_a_series_search_keeps_every_car_the_site_already_filtered():
    # "bmw 3er" named the group. Asking each ad to repeat "3er" in its title
    # would throw away every 3er, because dealers write the engine instead.
    parser = _StubbedParser([{"listings": [
        _bmw("a", "320 d HiFi NAVI"), _bmw("b", "318i Advantage"),
    ]}])
    found = asyncio.run(parser.search(SearchQuery(keywords="BMW 3er")))
    assert {item.external_id for item in found} == {"a", "b"}


def test_an_engine_variant_still_narrows_the_series():
    # "320d" is more specific than the group it selected, so it is checked —
    # against the dealer's spacing, not against ours.
    parser = _StubbedParser([{"listings": [
        _bmw("a", "320 d HiFi NAVI"), _bmw("b", "318i Advantage"),
    ]}])
    found = asyncio.run(parser.search(SearchQuery(keywords="BMW 320d")))
    assert [item.external_id for item in found] == ["a"]


def test_a_page_without_a_listings_key_counts_as_a_block():
    # An empty list means "no cars matched". A missing key means we were served
    # something that is not a result page — a captcha, an interstitial — and
    # calling that success resets the failure counter that raises the alarm.
    parser = _StubbedParser([{"numberOfResults": 0}])
    assert asyncio.run(parser.search(SearchQuery(keywords="Tesla Model 3"))) == []
    assert parser._suspect_block is True


def test_an_empty_result_page_is_not_a_block():
    parser = _StubbedParser([{"listings": []}])
    assert asyncio.run(parser.search(SearchQuery(keywords="Tesla Model 3"))) == []
    assert parser._suspect_block is False


def test_paging_stops_at_the_last_page():
    page_one = {"listings": [_card(id=f"a{i}") for i in range(20)]}
    page_two = {"listings": [_card(id=f"b{i}") for i in range(5)]}
    parser = _StubbedParser([page_one, page_two])
    found = asyncio.run(
        parser.search(SearchQuery(keywords="Tesla Model 3", max_results=40))
    )
    assert len(found) == 25
    assert sum("sort=age" in url for url in parser.requested) == 2
