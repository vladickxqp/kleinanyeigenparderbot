"""Mileage and registration-year bounds on a search rule.

The pipeline has read both values off car cards for a while — the price
comparison already uses them so a car is only measured against similar cars —
but a rule could not ask for them. With a car marketplace in the fleet that is
the first thing a buyer wants.

The rule these tests mostly defend: an ad that states neither value is KEPT.
Dropping it would make a markup change empty a paid rule overnight while every
health check stays green, which is the failure mode this project keeps meeting.
"""

from __future__ import annotations

from app.database.models.enums import Condition, SiteName
from app.parsers.schemas import ParsedListing, SearchQuery
from app.parsers.sites.autoscout24 import build_search_url
from app.parsers.sites.kleinanzeigen import KleinanzeigenParser
from app.services.parsing import parse_vehicle_bounds


def _query(**kwargs) -> SearchQuery:
    return SearchQuery(keywords="tesla model 3", **kwargs)


# --- The tri-state rule ----------------------------------------------------------
def test_a_car_inside_the_bounds_survives():
    query = _query(max_mileage_km=100_000, min_year=2018)
    assert query.matches_vehicle(80_000, 2020) is True
    assert query.matches_vehicle(100_000, 2018) is True  # bounds are inclusive


def test_a_car_outside_either_bound_is_dropped():
    query = _query(max_mileage_km=100_000, min_year=2018)
    assert query.matches_vehicle(140_000, 2020) is False
    assert query.matches_vehicle(80_000, 2015) is False


def test_an_ad_that_states_nothing_is_kept():
    # The whole point: unknown is not "too many kilometres". A site that stops
    # printing the mileage would otherwise silently empty the rule.
    query = _query(max_mileage_km=100_000, min_year=2018)
    assert query.matches_vehicle(None, None) is True
    assert query.matches_vehicle(None, 2020) is True
    assert query.matches_vehicle(140_000, None) is False  # the known half decides


def test_a_rule_without_bounds_judges_nothing():
    query = _query()
    assert query.wants_vehicle_filter is False
    assert query.matches_vehicle(500_000, 1990) is True


def test_one_bound_alone_works():
    assert _query(max_mileage_km=50_000).matches_vehicle(60_000, 1990) is False
    assert _query(min_year=2020).matches_vehicle(500_000, 2021) is True


# --- What the user types ---------------------------------------------------------
def test_size_decides_which_number_is_a_year():
    # "100000 2018" and "2018 100000" mean the same thing: nobody looks for a
    # car under 2.018 km, and everybody writes the year as four digits.
    assert parse_vehicle_bounds("100000 2018") == (100_000, 2018)
    assert parse_vehicle_bounds("2018 100000") == (100_000, 2018)
    assert parse_vehicle_bounds("100.000 km, ab 2018") == (100_000, 2018)


def test_a_single_number_is_read_by_its_size():
    assert parse_vehicle_bounds("100000") == (100_000, None)
    assert parse_vehicle_bounds("2018") == (None, 2018)
    assert parse_vehicle_bounds("ab 2018") == (None, 2018)


def test_nothing_usable_is_refused_rather_than_guessed():
    # A rejected input asks again; a guessed one stores a filter the user never
    # meant and then quietly returns nothing.
    assert parse_vehicle_bounds("") is None
    assert parse_vehicle_bounds("keine ahnung") is None
    assert parse_vehicle_bounds("-") is None


# --- AutoScout24 asks the site, then checks anyway ---------------------------------
def test_the_bounds_reach_the_autoscout24_url():
    url = build_search_url(
        _query(max_mileage_km=80_000, min_year=2022), make_id=51520, group_id=201429
    )
    assert "kmto=80000" in url
    assert "fregfrom=2022" in url


def test_a_rule_without_bounds_sends_no_vehicle_parameters():
    url = build_search_url(_query(), make_id=51520, group_id=None)
    assert "kmto=" not in url and "fregfrom=" not in url


def test_autoscout24_still_checks_what_it_asked_for():
    """A parameter the site quietly drops must not pass results through."""
    from app.parsers.sites.autoscout24 import AutoScout24Parser

    too_far = ParsedListing(
        site=SiteName.AUTOSCOUT24, external_id="a", title="Tesla Model 3",
        url="https://www.autoscout24.de/angebote/a", price=20000.0,
        mileage_km=180_000, registration_year=2020,
    )
    fine = too_far.model_copy(update={"external_id": "b", "mileage_km": 50_000})
    query = _query(max_mileage_km=100_000)
    assert AutoScout24Parser._wanted(too_far, query, []) is False
    assert AutoScout24Parser._wanted(fine, query, []) is True


# --- Kleinanzeigen filters locally ------------------------------------------------
KLEINANZEIGEN_CARS = """
<ul id="srchrslt-adtable">
  <article class="aditem" data-adid="1" data-href="/s-anzeige/a/1-216-1">
    <div class="aditem-main--middle">
      <h2><a class="ellipsis" href="/s-anzeige/a/1-216-1">Tesla Model 3 Long Range</a></h2>
      <div class="aditem-main--middle--price-shipping">
        <p class="aditem-main--middle--price-shipping--price">20.000 €</p>
      </div>
      <p class="text-module-end">
        <span class="simpletag">EZ 2020</span><span class="simpletag">60.000 km</span>
      </p>
    </div>
  </article>
  <article class="aditem" data-adid="2" data-href="/s-anzeige/b/2-216-1">
    <div class="aditem-main--middle">
      <h2><a class="ellipsis" href="/s-anzeige/b/2-216-1">Tesla Model 3 Standard</a></h2>
      <div class="aditem-main--middle--price-shipping">
        <p class="aditem-main--middle--price-shipping--price">15.000 €</p>
      </div>
      <p class="text-module-end">
        <span class="simpletag">EZ 2019</span><span class="simpletag">180.000 km</span>
      </p>
    </div>
  </article>
  <article class="aditem" data-adid="3" data-href="/s-anzeige/c/3-216-1">
    <div class="aditem-main--middle">
      <h2><a class="ellipsis" href="/s-anzeige/c/3-216-1">Tesla Model 3 ohne Angaben</a></h2>
      <div class="aditem-main--middle--price-shipping">
        <p class="aditem-main--middle--price-shipping--price">18.000 €</p>
      </div>
    </div>
  </article>
</ul>
"""


def _kleinanzeigen(query: SearchQuery) -> list[str]:
    parser = KleinanzeigenParser()
    items = parser._parse_results(KLEINANZEIGEN_CARS, query)
    return [
        item.external_id
        for item in items
        if query.matches_vehicle(item.mileage_km, item.registration_year)
    ]


def test_kleinanzeigen_reads_the_car_tags_and_honours_the_bounds():
    kept = _kleinanzeigen(_query(max_mileage_km=100_000, condition=Condition.ANY))
    # The 180.000-km car is out; the one without any tags stays, because
    # unknown is not a reason to throw an ad away.
    assert "2" not in kept
    assert "1" in kept and "3" in kept


def test_kleinanzeigen_year_bound():
    kept = _kleinanzeigen(_query(min_year=2020))
    assert "2" not in kept  # EZ 2019
    assert "1" in kept and "3" in kept
