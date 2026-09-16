"""The language picker promises four languages — these keep that promise."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from app.bot.formatting import format_deal_card, verdict_badge
from app.bot.texts import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, _TEXTS, t
from app.database.models import Flip, Listing, SiteName
from app.database.models.enums import DealVerdict
from app.services.flips import FlipStats


def test_every_key_exists_in_every_language():
    missing = [
        f"{key}:{lang}"
        for key, entry in _TEXTS.items()
        for lang in SUPPORTED_LANGUAGES
        if not entry.get(lang)
    ]
    assert missing == []


def test_placeholders_match_across_languages():
    """A translation that loses a placeholder would render a broken message."""
    pattern = re.compile(r"\{(\w+)\}")
    for key, entry in _TEXTS.items():
        expected = set(pattern.findall(entry[DEFAULT_LANGUAGE]))
        for lang in SUPPORTED_LANGUAGES:
            assert set(pattern.findall(entry[lang])) == expected, f"{key}/{lang}"


def test_unknown_key_and_language_degrade_gracefully():
    assert t("does.not.exist", "en") == "does.not.exist"
    assert t("card.auction", "fr") == t("card.auction", DEFAULT_LANGUAGE)
    assert t("card.auction", None) == t("card.auction", DEFAULT_LANGUAGE)


def _listing() -> Listing:
    return Listing(
        rule_id=1,
        site=SiteName.KLEINANZEIGEN,
        external_id="1",
        fingerprint="f",
        title="PS5 Slim",
        url="https://example.test/1",
        price=200.0,
        currency="EUR",
        original_price=260.0,
        estimated_market_price=300.0,
        discount_percent=33.0,
        deal_score=88,
        deal_verdict=DealVerdict.STEAL,
        shipping_cost=0.0,
        is_negotiable=True,
        is_auction=True,
    )


def test_deal_card_is_translated():
    """The card is the most-seen text in the product; it must follow the user."""
    listing = _listing()
    german = format_deal_card(listing, "de")
    english = format_deal_card(listing, "en")
    russian = format_deal_card(listing, "ru")

    assert "Marktpreis" in german and "Versand möglich" in german
    assert "Market price" in english and "Shipping available" in english
    assert "Рыночная цена" in russian and "Есть доставка" in russian

    # Structure stays identical in every language.
    for card in (german, english, russian):
        assert "88/100" in card
        assert 'href="https://example.test/1"' in card
        assert card.count("\n") == german.count("\n")


def test_verdict_badges_exist_for_every_verdict_and_language():
    for verdict in DealVerdict:
        for lang in SUPPORTED_LANGUAGES:
            badge = verdict_badge(verdict, lang)
            assert badge and badge != f"card.verdict.{verdict.value}"


# --- Whole screens, not just single keys ---------------------------------------
#
# A key can exist in four languages and the screen around it still be German:
# /flips, /support and /privacy used to build their pages from hardcoded German
# f-strings, so a reader who picked English got a German wall. The two tests
# below render those pages and refuse German wording in a non-German screen.

#: Words a non-German reader must never run into. Every one of them appeared in
#: the German-only versions of these pages.
GERMAN_TELLTALES = (
    "unbegrenzt", "heute", "Karten", "Suchen", "Monat",
    "Lager", "Gewinn", "Verkauft", "gekauft", "Nachricht", "gespeichert",
    "gelöscht", "Abbrechen", "Angebot",
)


def _stats(**overrides) -> FlipStats:
    values = dict(
        open_count=2, invested_open=340.0, sold_count=3, revenue=900.0,
        fees=45.0, net_profit=210.0, net_last_30d=120.0,
        best_title="PS5 Slim", best_net=90.0,
    )
    values.update(overrides)
    return FlipStats(**values)


def _empty_stats() -> FlipStats:
    return _stats(
        open_count=0, invested_open=0.0, sold_count=0, revenue=0.0, fees=0.0,
        net_profit=0.0, net_last_30d=0.0, best_title=None, best_net=None,
    )


def _open_flip() -> Flip:
    return Flip(
        id=1, telegram_id=1, title="PS5 Slim", buy_price=180.0,
        bought_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
    )


def _screens(lang: str) -> dict[str, str]:
    """Every page /flips, /support and /privacy can put on the screen."""
    from app.bot.handlers import flips, privacy

    return {
        "flips.inventory": flips.inventory_text([_open_flip()], _stats(), 50.0, lang),
        "flips.inventory_empty": flips.inventory_text([], _empty_stats(), None, lang),
        "flips.profit": flips.profit_text(_stats(), lang),
        "flips.profit_empty": flips.profit_text(_empty_stats(), lang),
        "flips.mode": flips.flip_mode_text(lang),
        "flips.ask_buy": t("flip.ask_buy_price", lang, title="PS5 Slim", price="200 €"),
        "flips.ask_sell": t("flip.ask_sell_price", lang, title="PS5 Slim", price="180 €"),
        "flips.bought": t(
            "flip.bought", lang, price="180 €", extra=t(
                "flip.expected_net", lang, market="300 €", net="90 €"
            ),
            open=1, invested="180 €", sold=t("flip.sold_word", lang),
        ),
        "flips.sold": t(
            "flip.sold_result", lang, icon="🎉", price="260 €", buy="180 €",
            fees="20 €", net="60 €", roi="+33%", total="210 €", count=3,
        ),
        "support.prompt": t("support.prompt", lang),
        "support.empty": t("support.empty", lang),
        "support.delivered": t("support.delivered", lang),
        "support.undelivered": t("support.undelivered", lang),
        "support.answer": t("support.answer", lang, text="It works again."),
        "privacy.page": privacy.privacy_text(lang),
        "privacy.export": t("privacy.export_caption", lang),
        "privacy.delete_confirm": t("privacy.delete_confirm", lang),
        "privacy.delete_aborted": t("privacy.delete_aborted", lang),
        "privacy.deleted": t("privacy.deleted", lang, name="Alex"),
    }


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_flip_support_and_privacy_screens_have_no_german_left(lang):
    for name, rendered in _screens(lang).items():
        lowered = rendered.lower()
        for word in GERMAN_TELLTALES:
            assert word.lower() not in lowered, f"{name}/{lang} still says '{word}'"


def test_every_screen_actually_changes_with_the_language():
    """Guards against a page that merely *looks* translated: no German word in
    it, because it is empty or English-ish by accident."""
    german = _screens(DEFAULT_LANGUAGE)
    for lang in SUPPORTED_LANGUAGES:
        if lang == DEFAULT_LANGUAGE:
            continue
        translated = _screens(lang)
        assert set(translated) == set(german)
        for name, rendered in translated.items():
            assert rendered.strip(), f"{name}/{lang} renders empty"
            assert rendered != german[name], f"{name}/{lang} is still the German text"


def test_translated_screens_keep_their_content():
    """The pages must stay the same pages — same commands, same numbers."""
    for lang in SUPPORTED_LANGUAGES:
        screens = _screens(lang)
        assert "/support" in screens["privacy.page"]
        assert "/meinedaten" in screens["privacy.page"]
        assert "/loeschen" in screens["privacy.page"]
        assert "/flips" in screens["flips.bought"]
        assert "180 €" in screens["flips.inventory"]
        assert "PS5 Slim" in screens["flips.inventory"]

    assert "In stock" in _screens("en")["flips.inventory"]
    assert "На складе" in _screens("ru")["flips.inventory"]
    assert "Your data" in _screens("en")["privacy.page"]
    assert "Твои данные" in _screens("ru")["privacy.page"]
