"""Optional AI deal analysis using Claude.

If ``AI_ENABLED`` is true and an API key is configured, this refines the heuristic
score with an LLM assessment (deal quality, resale probability, estimated profit).
Every failure path (disabled, missing SDK, API error, bad JSON) returns ``None`` so
callers transparently fall back to the deterministic heuristic scorer.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from loguru import logger

from app.config.settings import settings
from app.database.models.enums import DealVerdict
from app.parsers.schemas import ParsedListing
from app.services.price_analysis import PriceStats

_VERDICT_MAP = {v.value: v for v in DealVerdict}

_SYSTEM_PROMPT = (
    "You are a pricing expert for second-hand and retail marketplaces. "
    "Given an item and market statistics, judge how good the deal is. "
    "Respond ONLY with a compact JSON object, no prose, using exactly these keys: "
    '{"score": int 0-100, "verdict": one of '
    '["overpriced","fair","good","great","steal"], '
    '"resale_probability": float 0-1, "estimated_profit_eur": number, '
    '"reasoning": short string}. '
    "'steal' means an anomalously low price likely to be a seller mistake."
)


@dataclass(slots=True)
class AIScore:
    """Structured AI assessment of a listing."""

    score: int
    verdict: DealVerdict
    resale_probability: float
    estimated_profit_eur: float
    reasoning: str


def is_available() -> bool:
    """True if AI scoring is enabled and configured."""
    if not settings.ai_enabled or not settings.anthropic_api_key:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        logger.warning("AI enabled but 'anthropic' package not installed")
        return False
    return True


#: Every model call is bounded. A worker task is killed at 150s, so a hanging
#: request would take the whole task down with it instead of falling back.
DEFAULT_TIMEOUT_SECONDS = 20.0


async def ask(
    system: str,
    prompt: str,
    *,
    max_tokens: int = 300,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """One model call, bounded in time. Returns the text, or None on failure.

    The single place the SDK is spoken to: model, timeout and the "a failure is
    a None, not an exception" contract are decided here, so a second caller
    cannot quietly ship without a timeout.
    """
    if not is_available():
        return None
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await asyncio.wait_for(
        client.messages.create(
            model=settings.ai_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        ),
        timeout=timeout,
    )
    return "".join(block.text for block in message.content if block.type == "text")


async def score_listing_ai(listing: ParsedListing, stats: PriceStats) -> AIScore | None:
    """Ask Claude to assess a listing. Returns None on any failure."""
    try:
        text = await ask(_SYSTEM_PROMPT, _build_user_prompt(listing, stats))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - never let AI break the pipeline
        logger.warning("AI scoring failed, falling back to heuristic: {}", exc)
        return None
    return _parse_response(text) if text else None


def _build_user_prompt(listing: ParsedListing, stats: PriceStats) -> str:
    return json.dumps(
        {
            "title": listing.title,
            "price_eur": listing.price,
            "shipping_eur": listing.shipping_cost,
            "condition": listing.condition.value,
            "location": listing.location,
            "market": {
                "samples": stats.count,
                "median_eur": stats.median,
                "min_eur": stats.minimum,
                "max_eur": stats.maximum,
                "average_eur": stats.average,
            },
        },
        ensure_ascii=False,
    )


def _parse_response(text: str) -> AIScore | None:
    text = text.strip()
    # Be tolerant of accidental code fences.
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") : text.rfind("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("AI returned non-JSON: {!r}", text[:200])
        return None

    verdict = _VERDICT_MAP.get(str(data.get("verdict", "")).lower(), DealVerdict.UNKNOWN)
    try:
        return AIScore(
            score=int(max(0, min(100, data.get("score", 50)))),
            verdict=verdict,
            resale_probability=float(data.get("resale_probability", 0.0)),
            estimated_profit_eur=float(data.get("estimated_profit_eur", 0.0)),
            reasoning=str(data.get("reasoning", ""))[:280],
        )
    except (TypeError, ValueError):
        return None
