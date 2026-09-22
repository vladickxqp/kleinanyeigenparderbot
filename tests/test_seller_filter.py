"""Private seller or dealer — the single biggest predictor of a bargain.

A dealer prices to a margin and a warranty; a private seller prices to be rid
of the thing. AutoScout24 states which it is on every card and even filters on
it server-side, and the pipeline had nowhere to put the answer.

The rule these tests mostly defend is the same one the shipping and mileage
filters follow: an ad whose seller the marketplace does not name is KEPT. Most
marketplaces never say, and reading silence as "dealer" would empty a
"private only" rule on every one of them at once.
"""

from __future__ import annotations

import pytest

from app.database.models.enums import SellerType, SiteName
from app.parsers.schemas import ParsedListing, SearchQuery
from app.parsers.sites.autoscout24 import (
    AutoScout24Parser,
    _seller_type,
    build_search_url,
)


def _query(**kwargs) -> SearchQuery:
    return SearchQuery(keywords="tesla model 3", **kwargs)


def _listing(seller: SellerType | None) -> ParsedListing:
    return ParsedListing(
        site=SiteName.AUTOSCOUT24, external_id="a", title="Tesla Model 3",
        url="https://www.autoscout24.de/angebote/a", price=20000.0,
        seller_type=seller,
    )


# --- The tri-state rule -----------------------------------------------------------
def test_a_rule_without_a_preference_takes_everyone():
    query = _query()
    for seller in (SellerType.PRIVATE, SellerType.DEALER, None):
        assert query.matches_seller(seller) is True


def test_private_only_keeps_private_and_drops_dealers():
    query = _query(seller_type=SellerType.PRIVATE)
    assert query.matches_seller(SellerType.PRIVATE) is True
    assert query.matches_seller(SellerType.DEALER) is False


def test_dealers_only_is_the_mirror_image():
    query = _query(seller_type=SellerType.DEALER)
    assert query.matches_seller(SellerType.DEALER) is True
    assert query.matches_seller(SellerType.PRIVATE) is False


def test_an_ad_with_no_named_seller_is_kept():
    # The whole point. Kleinanzeigen, eBay and Idealo say nothing about who is
    # selling; dropping those would empty the rule everywhere but AutoScout24.
    assert _query(seller_type=SellerType.PRIVATE).matches_seller(None) is True
    assert _query(seller_type=SellerType.DEALER).matches_seller(None) is True
    assert _query(seller_type=SellerType.PRIVATE).matches_seller(SellerType.ANY) is True


# --- Reading AutoScout24's own wording --------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PrivateSeller", SellerType.PRIVATE),
        ("privateseller", SellerType.PRIVATE),
        ("Dealer", SellerType.DEALER),
        ("dealer", SellerType.DEALER),
    ],
)
def test_the_marketplace_wording_is_mapped(raw, expected):
    assert _seller_type({"type": raw}) is expected


def test_an_unknown_wording_stays_unknown():
    # A renamed type must not silently become "dealer" and empty every
    # private-only rule; unknown keeps the ad instead.
    assert _seller_type({"type": "Haendlerbetrieb"}) is None
    assert _seller_type({"type": ""}) is None
    assert _seller_type({}) is None


# --- Asked of the site, then checked anyway ---------------------------------------
def test_the_preference_reaches_the_autoscout24_url():
    private = build_search_url(
        _query(seller_type=SellerType.PRIVATE), make_id=51520, group_id=201429
    )
    assert "custtype=P" in private
    dealer = build_search_url(
        _query(seller_type=SellerType.DEALER), make_id=51520, group_id=201429
    )
    assert "custtype=D" in dealer


def test_no_preference_sends_no_parameter():
    url = build_search_url(_query(), make_id=51520, group_id=None)
    assert "custtype" not in url


def test_the_parser_checks_what_it_asked_for():
    """A parameter the site quietly drops must not pass results through."""
    query = _query(seller_type=SellerType.PRIVATE)
    assert AutoScout24Parser._wanted(_listing(SellerType.PRIVATE), query, []) is True
    assert AutoScout24Parser._wanted(_listing(SellerType.DEALER), query, []) is False
    # And an unnamed seller still survives the local check.
    assert AutoScout24Parser._wanted(_listing(None), query, []) is True


# --- The rule carries it ----------------------------------------------------------
def test_the_rule_default_is_any():
    from app.database.models import SearchRule

    rule = SearchRule(user_id=1, name="cars", keywords="tesla")
    # Set by the column default on INSERT; unset in memory means "not chosen".
    assert rule.seller_type in (None, SellerType.ANY)


def test_the_query_is_built_from_the_rule():
    from app.database.models import SearchRule
    from app.services.search_service import SearchService

    from app.database.models.enums import Condition

    rule = SearchRule(
        user_id=1, name="cars", keywords="tesla", seller_type=SellerType.PRIVATE,
        condition=Condition.ANY, exclude_auctions=False,
    )
    assert SearchService._build_query(rule).seller_type is SellerType.PRIVATE

    # A rule built in memory has no column defaults yet; "not chosen" must
    # still mean "any" rather than blowing up the query.
    unset = SearchRule(
        user_id=1, name="cars", keywords="tesla",
        condition=Condition.ANY, exclude_auctions=False,
    )
    assert SearchService._build_query(unset).seller_type is SellerType.ANY
