"""Imprint, terms and the withdrawal notice.

The page is assembled from the operator's own settings (see
:mod:`app.services.legal`). Nothing here invents legal content: when the
details are missing the command says the page does not exist yet, because a
heading with nothing under it reads like a legal notice and carries none of
its content.
"""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.texts import t
from app.services import legal

router = Router(name="legal")


def legal_text(lang: str | None = None) -> str:
    """The legal page, or the "not configured yet" note."""
    data = legal.imprint()
    if not data.is_complete:
        return t("legal.unconfigured", lang)

    blocks: list[str] = [t("legal.title", lang), ""]

    blocks.append(t("legal.imprint_head", lang))
    blocks.append(escape(data.operator))
    for line in data.address.splitlines():
        if line.strip():
            blocks.append(escape(line.strip()))

    contact = [f"✉️ {escape(data.email)}"]
    if data.phone:
        contact.append(f"☎️ {escape(data.phone)}")
    blocks += ["", t("legal.contact_head", lang), *contact]

    if data.register or data.vat_id:
        rows = [escape(value) for value in (data.register, data.vat_id) if value]
        blocks += ["", t("legal.register_head", lang), *rows]

    notice = legal.withdrawal_notice()
    if notice:
        blocks += ["", t("legal.withdrawal_head", lang), escape(notice)]

    links = []
    if data.terms_url:
        links.append(t("legal.terms_link", lang, url=escape(data.terms_url)))
    if data.privacy_url:
        links.append(t("legal.privacy_link", lang, url=escape(data.privacy_url)))
    if links:
        blocks += ["", *links]

    return "\n".join(blocks)


@router.message(Command("rechtliches", "legal", "impressum"))
async def cmd_legal(message: Message, lang: str) -> None:
    await message.answer(legal_text(lang), disable_web_page_preview=True)
