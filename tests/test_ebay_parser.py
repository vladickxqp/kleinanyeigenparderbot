"""Tests for the eBay parser using a static fixture snippet."""

from __future__ import annotations

from app.parsers.sites.ebay import EbayParser
from app.parsers.schemas import SearchQuery

SAMPLE_HTML = """
<ul>
  <li class="s-item s-item__pl-on-bottom">
    <div class="s-item__wrapper">
      <a class="s-item__link" href="https://www.ebay.de/itm/1234567890?hash=abc">
        <div class="s-item__image-wrapper">
          <img src="https://i.ebayimg.com/rtx.jpg" />
        </div>
        <div class="s-item__title"><span>Nvidia RTX 4090 24GB</span></div>
      </a>
      <div class="s-item__subtitle">Neu (Sonstige)</div>
      <span class="s-item__price">1.299,00 €</span>
      <span class="s-item__location s-item__itemLocation">aus Deutschland</span>
    </div>
  </li>
  <li class="s-item">
    <a class="s-item__link" href="https://www.ebay.de/itm/9876543210">
      <div class="s-item__title">Grafikkarte RTX 4090 OC</div>
    </a>
    <span class="s-item__price">EUR 1.150,00</span>
  </li>
</ul>
"""


def test_ebay_parses_cards():
    parser = EbayParser()
    listings = parser._parse_results(SAMPLE_HTML)
    assert len(listings) == 2

    first = listings[0]
    assert first.external_id == "1234567890"
    assert "RTX 4090" in first.title
    assert first.price == 1299.0
    assert str(first.image_url) == "https://i.ebayimg.com/rtx.jpg"
    assert first.location == "aus Deutschland"


def test_ebay_price_variants():
    parser = EbayParser()
    assert parser._parse_price("1.299,00 €") == 1299.0
    assert parser._parse_price("EUR 1.150,00") == 1150.0
    assert parser._parse_price(None) is None


def test_ebay_item_id_extraction():
    parser = EbayParser()
    assert parser._extract_item_id("https://www.ebay.de/itm/1234567890?x=1") == "1234567890"
    assert parser._extract_item_id("https://www.ebay.de/sch") is None


def test_ebay_build_url_includes_filters():
    parser = EbayParser()
    url = parser._build_url(SearchQuery(keywords="rtx 4090", max_price=1300, exclude_auctions=True))
    assert "_nkw=rtx+4090" in url
    assert "_udhi=1300" in url
    assert "LH_BIN=1" in url
