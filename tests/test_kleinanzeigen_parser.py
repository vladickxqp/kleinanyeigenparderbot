"""Tests for the Kleinanzeigen HTML parser using a static fixture snippet."""

from __future__ import annotations

from app.parsers.schemas import SearchQuery
from app.parsers.sites.kleinanzeigen import KleinanzeigenParser

# Minimal but representative slice of a Kleinanzeigen search results page.
SAMPLE_HTML = """
<ul id="srchrslt-adtable">
  <li class="ad-listitem">
    <article class="aditem" data-adid="123456789"
             data-href="/s-anzeige/rtx-4090/123456789-225-1234">
      <div class="aditem-image">
        <img src="https://img.kleinanzeigen.de/rtx.jpg" srcset="" />
      </div>
      <div class="aditem-main">
        <div class="aditem-main--top">
          <div class="aditem-main--top--left">10115 Berlin - Mitte</div>
        </div>
        <div class="aditem-main--middle">
          <h2 class="text-module-begin">
            <a class="ellipsis" href="/s-anzeige/rtx-4090/123456789-225-1234">
              Nvidia RTX 4090 Founders Edition
            </a>
          </h2>
          <p class="aditem-main--middle--description">
            Neuwertig, kaum benutzt, mit Rechnung.
          </p>
          <div class="aditem-main--middle--price-shipping">
            <p class="aditem-main--middle--price-shipping--price">1.150 € VB</p>
            <span class="aditem-main--middle--price-shipping--shipping">
              Versand möglich
            </span>
          </div>
        </div>
      </div>
    </article>
  </li>
</ul>
"""


def test_parse_results_extracts_expected_fields():
    parser = KleinanzeigenParser()
    query = SearchQuery(keywords="rtx 4090")
    listings = parser._parse_results(SAMPLE_HTML, query)

    assert len(listings) == 1
    item = listings[0]
    assert item.external_id == "123456789"
    assert "RTX 4090" in item.title
    assert item.price == 1150.0
    assert item.location == "10115 Berlin - Mitte"
    assert str(item.url).startswith("https://www.kleinanzeigen.de/")
    assert item.image_url is not None
    assert item.shipping_cost == 0.0  # "Versand möglich" detected


def test_price_parser_handles_variants():
    parser = KleinanzeigenParser()
    assert parser._parse_price("1.300 €") == 1300.0
    assert parser._parse_price("950 € VB") == 950.0
    assert parser._parse_price("Zu verschenken") is None
    assert parser._parse_price(None) is None


def test_build_url_encodes_price_and_keywords():
    parser = KleinanzeigenParser()
    url = parser._build_url(SearchQuery(keywords="rtx 4090", max_price=1300))
    assert "preis::1300" in url
    assert "rtx" in url.lower()
    # Wanted-ads (Gesuche) are excluded by default.
    assert "anzeige:angebote" in url


def test_build_url_with_category_location_radius():
    parser = KleinanzeigenParser()
    query = SearchQuery(
        keywords="iphone 17 pro",
        category="handys",
        max_distance_km=50,
    )
    url = parser._build_url(query, location_id="3331")
    assert url.endswith("k0c173l3331r50")


def test_build_url_without_location_has_plain_suffix():
    parser = KleinanzeigenParser()
    url = parser._build_url(SearchQuery(keywords="iphone"))
    assert url.endswith("k0")


def test_extract_location_id_live_shape():
    """Real payload shape verified against the live endpoint (2026-07):
    the id is embedded in the KEY, "_0" is the nationwide pseudo-entry."""
    data = {"_0": "Deutschland", "_5198": "67550 Worms"}
    assert KleinanzeigenParser._extract_location_id(data) == "5198"


def test_extract_location_id_skips_nationwide_entry():
    assert KleinanzeigenParser._extract_location_id({"_0": "Deutschland"}) is None


def test_extract_location_id_never_returns_the_zip_from_labels():
    # The label contains the zip code — it must NOT be mistaken for the id.
    data = {"_0": "Deutschland", "_4285": "67550 Worms, Rheinland-Pfalz"}
    assert KleinanzeigenParser._extract_location_id(data) == "4285"


def test_extract_location_id_legacy_shapes():
    assert KleinanzeigenParser._extract_location_id({"10115 Berlin": "l3331"}) == "3331"
    assert (
        KleinanzeigenParser._extract_location_id([{"id": "9282", "name": "München"}])
        == "9282"
    )
    assert KleinanzeigenParser._extract_location_id({}) is None


def test_vehicle_tags_are_prepended_to_description():
    """Car cards carry km + EZ as simpletag spans (verified live 2026-07)."""
    html = """
    <article class="aditem" data-adid="555000111"
             data-href="/s-anzeige/tesla/555000111-216-1">
      <div class="aditem-main">
        <div class="aditem-main--top">
          <div class="aditem-main--top--left">67550 Worms</div>
          <div class="aditem-main--top--right">Heute, 10:00</div>
        </div>
        <div class="aditem-main--middle">
          <h2><a class="ellipsis" href="/s-anzeige/tesla/555000111-216-1">
            Tesla Model 3 Long Range</a></h2>
          <p class="aditem-main--middle--description">Top Zustand, AHK.</p>
          <div class="aditem-main--middle--price-shipping">
            <p class="aditem-main--middle--price-shipping--price">27.900 €</p>
          </div>
        </div>
        <div class="aditem-main--bottom">
          <span class="simpletag">55.000 km</span>
          <span class="simpletag">EZ 09/2021</span>
        </div>
      </div>
    </article>
    """
    parser = KleinanzeigenParser()
    listings = parser._parse_results(html, SearchQuery(keywords="tesla model 3"))
    assert len(listings) == 1
    desc = listings[0].description
    assert desc is not None
    assert desc.startswith("55.000 km · EZ 09/2021")
    assert "Top Zustand" in desc
