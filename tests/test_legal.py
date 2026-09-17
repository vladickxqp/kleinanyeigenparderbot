"""Imprint, terms and the withdrawal notice.

The bot takes money from consumers in the EU, which needs an imprint (§5 DDG)
and a withdrawal notice (§312g, §356 Abs. 5 BGB). This repository cannot supply
either: they name a real operator at a real address, and a wrong one is worse
than a missing one, because it names somebody who never agreed to be named.

So the content comes from settings and the tests below pin down the two things
code CAN be responsible for: never presenting a half-filled page as a legal
notice, and never letting the gap go unnoticed until after go-live.
"""

from __future__ import annotations

import pytest

from app.bot.handlers.legal import legal_text
from app.bot.texts import SUPPORTED_LANGUAGES, t
from app.config.settings import settings
from app.services import legal


@pytest.fixture()
def configured(monkeypatch):
    """A fully configured operator, as an .env would supply it."""
    values = {
        "legal_operator": "Beispiel GmbH",
        "legal_address": "Musterstr. 1\n67547 Worms",
        "legal_email": "kontakt@example.de",
        "legal_phone": "+49 151 000000",
        "legal_register": "HRB 12345, AG Mainz",
        "legal_vat_id": "DE123456789",
        "legal_terms_url": "https://example.de/agb",
        "legal_privacy_url": "https://example.de/datenschutz",
        "legal_withdrawal": "Der Widerruf erlischt bei sofortiger Ausführung.",
        "legal_version": "",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    return values


@pytest.fixture()
def unconfigured(monkeypatch):
    for key in (
        "legal_operator", "legal_address", "legal_email", "legal_phone",
        "legal_register", "legal_vat_id", "legal_terms_url",
        "legal_privacy_url", "legal_withdrawal", "legal_version",
    ):
        monkeypatch.setattr(settings, key, "")


# --- Nothing is invented ----------------------------------------------------------
def test_an_unconfigured_page_says_so_instead_of_pretending(unconfigured):
    """Headings with nothing under them read like a legal notice and are not one."""
    page = legal_text("de")
    assert page == t("legal.unconfigured", "de")
    assert "Anbieter" not in page
    assert "Widerruf" not in page


def test_a_half_filled_operator_is_not_a_page_either(unconfigured, monkeypatch):
    # A name without an address identifies nobody — §5 DDG wants both.
    monkeypatch.setattr(settings, "legal_operator", "Beispiel GmbH")
    assert legal_text("de") == t("legal.unconfigured", "de")
    assert legal.is_complete() is False


def test_the_page_carries_exactly_what_was_configured(configured):
    page = legal_text("de")
    assert "Beispiel GmbH" in page
    assert "Musterstr. 1" in page and "67547 Worms" in page
    assert "kontakt@example.de" in page
    assert "+49 151 000000" in page
    assert "HRB 12345" in page and "DE123456789" in page
    assert "Der Widerruf erlischt" in page
    assert "https://example.de/agb" in page


def test_optional_details_are_left_out_when_absent(configured, monkeypatch):
    monkeypatch.setattr(settings, "legal_register", "")
    monkeypatch.setattr(settings, "legal_vat_id", "")
    monkeypatch.setattr(settings, "legal_phone", "")
    page = legal_text("de")
    # Still a valid page: register and VAT id are only required if they exist.
    assert "Beispiel GmbH" in page
    assert t("legal.register_head", "de") not in page
    assert "☎️" not in page


def test_the_operator_s_own_words_are_escaped(configured, monkeypatch):
    # An operator name with an ampersand would otherwise break Telegram's HTML
    # parser and the page would never arrive.
    monkeypatch.setattr(settings, "legal_operator", "Meier & Söhne <GmbH>")
    page = legal_text("de")
    assert "Meier &amp; Söhne &lt;GmbH&gt;" in page
    assert "<GmbH>" not in page


def test_the_page_is_translated(configured):
    pages = {lang: legal_text(lang) for lang in SUPPORTED_LANGUAGES}
    for lang, page in pages.items():
        assert "Beispiel GmbH" in page, lang  # the data never changes
        assert page.strip()
    assert len({page for page in pages.values()}) == len(SUPPORTED_LANGUAGES)


# --- The gap must be loud ---------------------------------------------------------
def test_missing_fields_are_named_one_by_one(unconfigured):
    gaps = legal.missing(for_sale=True)
    assert "legal_operator" in gaps
    assert "legal_withdrawal" in gaps
    # The imprint alone does not need a withdrawal notice; a sale does.
    assert "legal_withdrawal" not in legal.missing()


def test_a_complete_setup_reports_no_gaps(configured):
    assert legal.missing(for_sale=True) == []
    assert legal.is_complete(for_sale=True) is True


def test_selling_needs_more_than_an_imprint(configured, monkeypatch):
    monkeypatch.setattr(settings, "legal_withdrawal", "")
    assert legal.is_complete() is True          # the page itself is fine
    assert legal.is_complete(for_sale=True) is False  # selling is not


# --- What the customer was shown has to stay checkable ----------------------------
def test_the_version_follows_the_texts_when_nobody_maintains_it(configured, monkeypatch):
    first = legal.version()
    assert first.startswith("auto-")
    monkeypatch.setattr(settings, "legal_withdrawal", "Ein anderer Text.")
    assert legal.version() != first


def test_an_explicit_version_wins(configured, monkeypatch):
    monkeypatch.setattr(settings, "legal_version", "2026-09-17")
    assert legal.version() == "2026-09-17"


def test_an_unconfigured_setup_has_no_version_to_record(unconfigured):
    assert legal.version() == ""


# --- The purchase page ------------------------------------------------------------
def test_the_purchase_hint_appears_only_once_there_is_something_to_point_at(
    configured, monkeypatch
):
    from app.bot.handlers import premium as premium_view

    assert premium_view._legal_note("de") == t("legal.before_purchase", "de")
    monkeypatch.setattr(settings, "legal_withdrawal", "")
    # A hint linking to an empty page is worse than no hint.
    assert premium_view._legal_note("de") == ""
