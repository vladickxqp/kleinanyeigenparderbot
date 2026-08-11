"""Photo assessment: identify a product on an image and estimate its value.

Uses Claude's vision capability through the same optional AI setup as the
deal scorer (``AI_ENABLED`` + ``ANTHROPIC_API_KEY``). Every failure path
returns ``None`` so the bot can answer gracefully instead of crashing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger

from app.config.settings import settings

_SYSTEM_PROMPT = (
    "You are an expert for second-hand marketplace pricing in Germany. "
    "Identify the product on the photo as precisely as possible (brand, model, "
    "variant) and estimate its current used-market value in EUR. "
    "Respond ONLY with a compact JSON object, no prose, exactly these keys: "
    '{"product": string, "search_query": string (2-5 German search words for '
    'kleinanzeigen.de), "est_value_eur": number or null, '
    '"confidence": "low"|"medium"|"high", "notes": short German string '
    "(condition hints visible on the photo, what to check before buying)}."
)


@dataclass(slots=True)
class PhotoAssessment:
    """Structured result of a photo evaluation."""

    product: str
    search_query: str
    est_value_eur: float | None
    confidence: str
    notes: str


def _parse_response(text: str) -> PhotoAssessment | None:
    """Parse the model's JSON answer (tolerates accidental code fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("vision returned non-JSON: {!r}", text[:200])
        return None
    product = str(data.get("product", "")).strip()
    query = str(data.get("search_query", "")).strip()
    if not product or not query:
        return None
    raw_value = data.get("est_value_eur")
    try:
        value = float(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None
    confidence = str(data.get("confidence", "low")).lower()
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    return PhotoAssessment(
        product=product[:120],
        search_query=query[:100],
        est_value_eur=value,
        confidence=confidence,
        notes=str(data.get("notes", ""))[:300],
    )


async def assess_photo(
    image_b64: str, media_type: str = "image/jpeg", caption: str | None = None
) -> PhotoAssessment | None:
    """Identify the product on a photo. Returns None on any failure."""
    from app.services.ai import is_available

    if not is_available():
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        user_text = "Identifiziere das Produkt und schätze den Gebrauchtwert."
        if caption:
            user_text += f" Hinweis des Nutzers: {caption[:200]}"
        message = await client.messages.create(
            model=settings.ai_model,
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
        text = "".join(b.text for b in message.content if b.type == "text")
        return _parse_response(text)
    except Exception as exc:  # noqa: BLE001 - never break the bot over vision
        logger.warning("Photo assessment failed: {}", exc)
        return None
