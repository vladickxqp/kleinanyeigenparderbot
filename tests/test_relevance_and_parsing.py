"""Tests for the relevance filter (accessory noise) and price-range parsing."""

from __future__ import annotations

from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing, SearchQuery
from app.services.parsing import parse_price_range
from app.services.relevance import filter_relevant, is_relevant


def _item(title: str, price: float | None = 900.0, desc: str | None = None) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id=title,
        title=title,
        url="https://www.kleinanzeigen.de/x",
        price=price,
        description=desc,
    )


# --- Relevance: the "iPhone 17 Pro -> Hülle" bug -------------------------------
def test_accessory_case_is_filtered():
    q = SearchQuery(keywords="iphone 17 pro")
    assert is_relevant(q, _item("Hülle für iPhone 17 Pro", 15.0)) is False
    assert is_relevant(q, _item("Panzerglas iPhone 17 Pro", 9.0)) is False
    assert is_relevant(q, _item("Ladekabel für iPhone 17 Pro", 5.0)) is False


def test_real_product_passes():
    q = SearchQuery(keywords="iphone 17 pro")
    assert is_relevant(q, _item("iPhone 17 Pro 256GB Schwarz", 950.0)) is True
    assert is_relevant(q, _item("Apple iPhone 17 Pro wie neu", 899.0)) is True


def test_accessory_search_still_finds_accessories():
    # If the user explicitly searches for a case, cases must NOT be filtered.
    q = SearchQuery(keywords="iphone 17 pro hülle")
    assert is_relevant(q, _item("Hülle für iPhone 17 Pro", 15.0)) is True


def test_all_keywords_must_be_present():
    q = SearchQuery(keywords="iphone 17 pro")
    # Plain "iPhone 17" without "Pro" is a different product.
    assert is_relevant(q, _item("iPhone 17 128GB", 700.0)) is False


# --- Variant matching: "tesla model 3" must find Performance/Long Range --------
def test_variants_with_extra_words_match():
    q = SearchQuery(keywords="tesla model 3")
    assert is_relevant(q, _item("Tesla Model 3 Performance", 32000.0)) is True
    assert is_relevant(q, _item("Tesla Model 3 Long Range AWD", 32000.0)) is True


def test_missing_brand_in_title_still_matches():
    # Sellers often omit the brand: "Model 3 Performance, Bj. 2022".
    q = SearchQuery(keywords="tesla model 3")
    assert is_relevant(q, _item("Model 3 Performance, Bj. 2022", 30000.0)) is True


def test_missing_model_token_does_not_match():
    q = SearchQuery(keywords="tesla model 3")
    # "Model S" is a different car — the "3" is mandatory.
    assert is_relevant(q, _item("Tesla Model S 2021", 35000.0)) is False


def test_two_token_queries_stay_strict():
    q = SearchQuery(keywords="rtx 4090")
    assert is_relevant(q, _item("RTX 3090 24GB", 800.0)) is False


def test_wanted_ads_are_filtered():
    q = SearchQuery(keywords="iphone 17 pro")
    assert is_relevant(q, _item("Suche iPhone 17 Pro", 1.0)) is False


def test_filter_relevant_batch():
    q = SearchQuery(keywords="rtx 4090")
    items = [
        _item("RTX 4090 Founders Edition", 1200.0),
        _item("Halterung für RTX 4090", 12.0),
        _item("Suche RTX 4090", 1.0),
    ]
    kept = filter_relevant(q, items)
    assert [i.title for i in kept] == ["RTX 4090 Founders Edition"]


# --- Price range parsing --------------------------------------------------------
def test_plain_number_is_max():
    assert parse_price_range("1200") == (None, 1200.0)
    assert parse_price_range("1200 €") == (None, 1200.0)


def test_range():
    assert parse_price_range("500-1200") == (500.0, 1200.0)
    assert parse_price_range("1200-500") == (500.0, 1200.0)  # swapped bounds


def test_min_only():
    assert parse_price_range("ab 500") == (500.0, None)
    assert parse_price_range("500+") == (500.0, None)


def test_max_only_with_bis():
    assert parse_price_range("bis 1200") == (None, 1200.0)


def test_garbage_returns_none():
    assert parse_price_range("keine ahnung") is None
    assert parse_price_range("") is None


def test_space_separated_min_max():
    assert parse_price_range("18000 20000") == (18000.0, 20000.0)


def test_german_thousands_format():
    assert parse_price_range("18.000-20.000") == (18000.0, 20000.0)
    assert parse_price_range("18.000 20.000") == (18000.0, 20000.0)
    assert parse_price_range("1.200") == (None, 1200.0)
    assert parse_price_range("ab 18.000") == (18000.0, None)


def test_comma_as_separator_and_decimal():
    assert parse_price_range("18000, 20000") == (18000.0, 20000.0)
    assert parse_price_range("18000,20000") == (18000.0, 20000.0)
    assert parse_price_range("1200,50") == (None, 1200.5)


def test_mixed_german_full_format():
    assert parse_price_range("18.000 € - 20.000 €") == (18000.0, 20000.0)
