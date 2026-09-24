"""Kleinanzeigen's 2026 result page, as served on 2026-09-24.

The classic ``article.aditem`` markup is gone from the live site. The new page
is built from utility classes that carry no meaning, so the parser reads the
cards by what they say. The fixture below is a trimmed copy of a real card —
the same element order, the same texts — and pins down every field the
pipeline depends on: id, title, price, negotiable, date, location, shipping,
description, image and the vehicle tags.

The old fixtures stay in ``test_kleinanzeigen_parser.py``: both layouts are
read, because a restyle can be rolled back or served to part of the traffic.
"""

from __future__ import annotations

from datetime import datetime

from app.parsers.schemas import SearchQuery
from app.parsers.sites.kleinanzeigen import KleinanzeigenParser

# --- Fixtures ------------------------------------------------------------------------
CARD = """
<article class="flex justify-between p-medium" data-adid="3521734685"
         data-href="/s-anzeige/ps5-slim-disc-1tb/3521734685-279-1234">
  <div class="relative z-raised basis-[200px]">
    <script type="application/ld+json">{"creditText":"Kleinanzeigen","title":"PS5 Slim Disc 1TB",
      "description":"Verkaufe meine PS5 Slim mit Laufwerk. Der linke Stick vom Controller hat leichten Drift, Konsole selbst top.",
      "contentUrl":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/aa/aa11?rule=$_59.AUTO",
      "representativeOfPage":false,"@context":"https://schema.org","@type":"ImageObject"}</script>
    <a class="inline-flex items-center gap-xxsmall" href="/s-anzeige/ps5-slim-disc-1tb/3521734685-279-1234">
      <div class="relative flex h-[150px] w-[200px]" data-image-container="">
        <img alt="PS5 Slim Disc 1TB Vorschau" class="size-full object-cover"
             src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/aa/aa11?rule=$_2.AUTO"
             srcset="https://img.kleinanzeigen.de/api/v1/prod-ads/images/aa/aa11?rule=$_35.AUTO"/>
        <div class="absolute bottom-xsmall right-xsmall">4</div>
      </div>
    </a>
  </div>
  <div class="z-raised flex grow basis-[398px] flex-col overflow-hidden pl-medium">
    <div class="mb-xsmall flex items-start justify-between text-bodyRegular">
      <div class="flex items-center gap-xxsmall text-onSurfaceNonessential">
        <svg aria-hidden="true" data-title="locationOutline" viewbox="0 0 24 24"><path d="M1 1"/></svg>
        <span>67550 Worms</span>
      </div>
      <div class="flex items-center gap-xxsmall text-onSurfaceNonessential">
        <span>Heute, 12:05</span>
      </div>
    </div>
    <div class="flex flex-col">
      <h3 class="mb-xsmall line-clamp-2 text-title3 font-strong">
        <a class="inline-flex items-center gap-xxsmall" href="/s-anzeige/ps5-slim-disc-1tb/3521734685-279-1234">PS5 Slim Disc 1TB</a>
      </h3>
      <p class="mb-xsmall text-bodyRegular text-onSurfaceSubdued">Verkaufe meine PS5 Slim mit Laufwerk. Der linke Stick vom...</p>
      <div class="flex">
        <p class="my-xsmall text-title3 font-strong text-secondary">250 € VB</p>
      </div>
    </div>
    <div>
      <p class="flex">
        <span class="mr-xsmall inline-flex w-fit">Versand möglich</span>
      </p>
    </div>
  </div>
</article>
"""

CAR = """
<article class="flex justify-between p-medium" data-adid="3600000001"
         data-href="/s-anzeige/tesla-model-3-long-range/3600000001-216-9">
  <div class="z-raised flex grow flex-col">
    <div class="mb-xsmall flex items-start justify-between">
      <div class="flex items-center gap-xxsmall">
        <svg data-title="locationOutline"><path d="M1 1"/></svg>
        <span>10115 Berlin - Mitte</span>
      </div>
      <div class="flex items-center gap-xxsmall"><span>Gestern, 21:08</span></div>
    </div>
    <div class="flex flex-col">
      <h3 class="text-title3"><a href="/s-anzeige/tesla-model-3-long-range/3600000001-216-9">Tesla Model 3 Long Range</a></h3>
      <p class="text-bodyRegular">Top Zustand, AHK, 8-fach bereift.</p>
      <div class="flex"><p class="text-title3 font-strong">27.900 €</p></div>
    </div>
    <div class="flex gap-xsmall">
      <span class="rounded-xsmall">55.000 km</span>
      <span class="rounded-xsmall">EZ 09/2021</span>
      <span class="rounded-xsmall">Nur Abholung</span>
    </div>
  </div>
</article>
"""

PAGE = """
<html><body id="srchrslt" class="bg-background">
<h1>Mehr als 10.000 Ergebnisse – „ps5“</h1>
<input id="srchrslt-brwse-price-min"/><input id="srchrslt-brwse-price-max"/>
<ul class="list-none">{cards}</ul>
<a href="/s-anzeige:angebote/sortierung:neueste/ps5/seite:2/k0">Nächste</a>
</body></html>
"""

# The page the bot's own URLs receive (``s-anzeige:angebote/sortierung:neueste/…``):
# ``body#srp``, cards as <li>, meaningful classes, the FULL description behind a
# "..." button — and the <li> elements left unclosed, exactly as served.
SRP_PAGE = """
<html><body id="srp">
<main id="page-content">
<h1>240 Ergebnisse – „tesla model 3“</h1>
<ul id="srp-results">
<li class="j-adlistitem adlist--item" data-adid="3521754278" data-href="/s-anzeige/tesla-model-3-rwd/3521754278-216-2">
  <div class="adlist--item--imagebox">
    <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/t1?rule=$_2.AUTO"
         srcset="https://img.kleinanzeigen.de/api/v1/prod-ads/images/t1?rule=$_35.AUTO"/>
    <div class="has-image-count">12</div>
  </div>
  <div class="adlist--item--descarea">
    <div class="adlist--item--info">
      <div class="adlist--item--info--location">Seesen</div>
      <div class="adlist--item--info--date">Heute, 11:45</div>
    </div>
    <strong class="adlist--item--boldtitle"><a href="/s-anzeige/tesla-model-3-rwd/3521754278-216-2">Tesla Model 3 RWD Ryzen! LFP!</a></strong>
    <div class="adlist--item--description">
      <div class="description-preview">1.HAND! LFP! AMD-Ryzen<button class="adlist--item--more">...</button></div>
      <div class="long-description">1.HAND! LFP! AMD-Ryzen-Prozessor!<br><br>Wärmepumpe! Kein Unfall, kein Versand nötig.<br>Nur Abholung ist Prosa, kein Marker.</div>
    </div>
    <div class="adlist--item--price">25.999 €</div>
    <div class="adlist--item--attributes">
      <span class="simpletag">65.230 km</span>
      <span class="simpletag">EZ 03/2022</span>
    </div>
  </div>
<li class="j-adlistitem adlist--item" data-adid="3521780221" data-href="/s-anzeige/ps5-controller-weiss/3521780221-279-1649">
  <div class="adlist--item--imagebox">
    <img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/c1?rule=$_2.AUTO"/>
  </div>
  <div class="adlist--item--descarea">
    <div class="adlist--item--info">
      <div class="adlist--item--info--location">Rheda-Wiedenbrück</div>
      <div class="adlist--item--info--date">Gestern, 09:12</div>
    </div>
    <strong class="adlist--item--boldtitle"><a href="/s-anzeige/ps5-controller-weiss/3521780221-279-1649">Ps5 Controller Weiss</a></strong>
    <div class="adlist--item--description">
      <div class="description-preview">Hallo zusammen,<button class="adlist--item--more">...</button></div>
      <div class="long-description">Hallo zusammen,<br><br>fast nagelneuer Controller, Stick-Drift links.</div>
    </div>
    <div class="adlist--item--price">45 € VB</div>
    <div class="adlist--item--attributes">
      <span class="simpletag">Versand möglich</span>
    </div>
  </div>
</ul>
</main></body></html>
"""


def _parse(html: str, keywords: str = "ps5"):
    parser = KleinanzeigenParser()
    return parser, parser._parse_results(html, SearchQuery(keywords=keywords))


# --- The card -------------------------------------------------------------------------
def test_every_field_is_read_from_the_new_card():
    _, items = _parse(PAGE.format(cards=CARD))
    assert len(items) == 1
    item = items[0]
    assert item.external_id == "3521734685"
    assert item.title == "PS5 Slim Disc 1TB"
    assert str(item.url) == "https://www.kleinanzeigen.de/s-anzeige/ps5-slim-disc-1tb/3521734685-279-1234"
    assert item.price == 250.0
    assert item.is_negotiable is True
    assert item.is_auction is False
    assert item.location == "67550 Worms"
    assert item.shipping_available is True
    assert item.shipping_cost == 0.0


def test_the_date_is_today_at_the_stated_time():
    _, items = _parse(PAGE.format(cards=CARD))
    posted = items[0].posted_at
    assert isinstance(posted, datetime)
    assert (posted.hour, posted.minute) == (12, 5)
    assert posted.date() == datetime.now().date()


def test_the_longer_description_wins_because_the_defect_is_in_the_cut_off_part():
    _, items = _parse(PAGE.format(cards=CARD))
    desc = items[0].description or ""
    # The visible paragraph ends in "..."; the embedded object carries the rest.
    assert "Drift" in desc
    assert not desc.endswith("...")


def test_the_large_image_is_preferred_over_the_thumbnail():
    _, items = _parse(PAGE.format(cards=CARD))
    assert items[0].image_url is not None and "$_59" in str(items[0].image_url)


def test_a_price_inside_the_description_is_not_the_price():
    card = CARD.replace(
        "Verkaufe meine PS5 Slim mit Laufwerk. Der linke Stick vom...",
        "Neupreis war 549 €, jetzt günstig abzugeben...",
    )
    _, items = _parse(PAGE.format(cards=card))
    assert items[0].price == 250.0


def test_free_and_price_on_request_are_understood():
    free = CARD.replace("250 € VB", "Zu verschenken")
    _, items = _parse(PAGE.format(cards=free))
    assert items[0].price is None
    vb = CARD.replace("250 € VB", "VB")
    _, items = _parse(PAGE.format(cards=vb))
    assert items[0].price is None and items[0].is_negotiable is True


# --- Shipping, three ways ---------------------------------------------------------------
def test_nur_abholung_is_a_known_no_and_silence_is_unknown():
    _, cars = _parse(PAGE.format(cards=CAR), keywords="tesla model 3")
    assert cars[0].shipping_available is False
    silent = CARD.replace("Versand möglich", "")
    _, items = _parse(PAGE.format(cards=silent))
    assert items[0].shipping_available is None


# --- Vehicles ---------------------------------------------------------------------------
def test_vehicle_tags_are_read_without_the_simpletag_class():
    _, cars = _parse(PAGE.format(cards=CAR), keywords="tesla model 3")
    car = cars[0]
    assert car.mileage_km == 55000
    assert car.registration_year == 2021
    assert (car.description or "").startswith("55.000 km · EZ 09/2021")
    assert car.price == 27900.0
    assert car.location == "10115 Berlin - Mitte"
    assert car.posted_at is not None and (car.posted_at.hour, car.posted_at.minute) == (21, 8)


# --- The srp page (what the bot's own URLs receive) --------------------------------------
def test_unclosed_list_items_are_still_separate_ads():
    """lxml nests every <li> in the one before it; each ad must stay its own."""
    parser, items = _parse(SRP_PAGE, keywords="tesla model 3")
    assert parser._suspect_block is False
    assert [i.external_id for i in items] == ["3521754278", "3521780221"]


def test_srp_fields_do_not_bleed_from_the_next_ad():
    _, items = _parse(SRP_PAGE, keywords="tesla model 3")
    car, pad = items
    assert car.title == "Tesla Model 3 RWD Ryzen! LFP!"
    assert car.price == 25999.0 and car.is_negotiable is False
    assert car.location == "Seesen"
    assert car.posted_at is not None and (car.posted_at.hour, car.posted_at.minute) == (11, 45)
    assert car.mileage_km == 65230 and car.registration_year == 2022
    # "Versand möglich" belongs to the controller three lines down, not the car;
    # and "kein Versand" / "Nur Abholung" inside the prose are not markers.
    assert car.shipping_available is None
    assert pad.shipping_available is True
    assert pad.price == 45.0 and pad.is_negotiable is True
    assert pad.location == "Rheda-Wiedenbrück"


def test_srp_ships_the_full_description_not_the_teaser():
    _, items = _parse(SRP_PAGE, keywords="tesla model 3")
    car, pad = items
    assert "Wärmepumpe" in (car.description or "")
    assert "..." not in (pad.description or "")
    assert "Stick-Drift" in (pad.description or "")
    assert str(car.url) == "https://www.kleinanzeigen.de/s-anzeige/tesla-model-3-rwd/3521754278-216-2"
    assert car.image_url is not None and str(car.image_url).startswith("https://img.kleinanzeigen.de/")


def test_an_empty_srp_page_is_not_a_block():
    parser, items = _parse('<html><body id="srp"><ul id="srp-results"></ul></body></html>')
    assert items == [] and parser._suspect_block is False


# --- The page itself ---------------------------------------------------------------------
def test_an_empty_new_page_is_not_mistaken_for_a_block():
    parser, items = _parse(PAGE.format(cards=""))
    assert items == []
    assert parser._suspect_block is False


def test_a_page_with_nothing_we_recognise_is_a_block_signal():
    parser, items = _parse("<html><body><h1>Einen Moment bitte</h1></body></html>")
    assert items == []
    assert parser._suspect_block is True


def test_a_promoted_ad_without_a_date_still_parses():
    dateless = CARD.replace("<span>Heute, 12:05</span>", "")
    _, items = _parse(PAGE.format(cards=dateless))
    assert len(items) == 1
    assert items[0].posted_at is None


def test_both_layouts_on_one_page_are_both_read():
    classic = """
    <article class="aditem" data-adid="1" data-href="/s-anzeige/x/1-1-1">
      <div class="aditem-main"><div class="aditem-main--top">
        <div class="aditem-main--top--left">10115 Berlin</div></div>
        <div class="aditem-main--middle"><h2><a class="ellipsis" href="/s-anzeige/x/1-1-1">PS5 alt</a></h2>
        <div class="aditem-main--middle--price-shipping">
          <p class="aditem-main--middle--price-shipping--price">300 €</p></div></div></div>
    </article>
    """
    _, items = _parse(PAGE.format(cards=classic + CARD))
    assert [i.external_id for i in items] == ["1", "3521734685"]
    assert [i.price for i in items] == [300.0, 250.0]
