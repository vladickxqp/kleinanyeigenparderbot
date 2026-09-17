"""Imprint, terms and the withdrawal notice — assembled, never invented.

Selling a digital service to consumers in the EU needs three things this
repository cannot supply: an imprint (§5 DDG), terms, and a withdrawal notice
(§312g, §356 Abs. 5 BGB). They identify a real operator at a real address, and
a wrong one is worse than a missing one — it names somebody who never agreed to
be named.

So every field lives in settings and starts empty, and this module only ever
assembles what is actually there. Two rules follow from that:

* **A page that is not configured does not exist.** ``/rechtliches`` says so
  plainly instead of rendering headings with nothing under them, which would
  read like a legal page and carry none of its content.
* **Missing details are loud, not silent.** :func:`missing` feeds the admin
  status screen, because the one way this ends badly is going live without
  noticing.

What the code CAN do, and does: record which version of these texts a customer
was shown when they paid (:func:`version`). Without that, "the notice was
displayed" is a claim nobody can check afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import settings

#: Fields §5 DDG requires from any commercial provider. Register and VAT id are
#: deliberately not in here: they are required only if the operator has them.
REQUIRED_FIELDS: tuple[str, ...] = (
    "legal_operator",
    "legal_address",
    "legal_email",
)

#: What a purchase has to be able to point at.
REQUIRED_FOR_SALE: tuple[str, ...] = REQUIRED_FIELDS + ("legal_withdrawal",)


@dataclass(frozen=True, slots=True)
class Imprint:
    """The operator's details, as far as they are configured."""

    operator: str
    address: str
    email: str
    phone: str
    register: str
    vat_id: str
    terms_url: str
    privacy_url: str

    @property
    def is_complete(self) -> bool:
        return bool(self.operator and self.address and self.email)


def _value(field: str) -> str:
    return str(getattr(settings, field, "") or "").strip()


def imprint() -> Imprint:
    return Imprint(
        operator=_value("legal_operator"),
        address=_value("legal_address"),
        email=_value("legal_email"),
        phone=_value("legal_phone"),
        register=_value("legal_register"),
        vat_id=_value("legal_vat_id"),
        terms_url=_value("legal_terms_url"),
        privacy_url=_value("legal_privacy_url"),
    )


def withdrawal_notice() -> str:
    """The operator's withdrawal notice, or "" when none is configured."""
    return _value("legal_withdrawal")


def missing(for_sale: bool = False) -> list[str]:
    """Which required fields are still empty.

    ``for_sale`` adds what a purchase needs on top of the imprint.
    """
    fields = REQUIRED_FOR_SALE if for_sale else REQUIRED_FIELDS
    return [field for field in fields if not _value(field)]


def is_complete(for_sale: bool = False) -> bool:
    return not missing(for_sale=for_sale)


def version() -> str:
    """Which version of the legal texts is in force right now.

    Falls back to a fingerprint of the texts themselves, so a payment record
    still says what the customer was shown even when nobody maintains the
    version field by hand.
    """
    configured = _value("legal_version")
    if configured:
        return configured[:32]
    parts = [_value(field) for field in REQUIRED_FOR_SALE]
    if not any(parts):
        return ""
    import hashlib

    digest = hashlib.sha256("\n--\n".join(parts).encode("utf-8")).hexdigest()
    return "auto-" + digest[:12]
