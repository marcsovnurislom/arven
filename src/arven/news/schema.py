"""The fixed schema an LLM may ever structure a news item into (CLAUDE.md rule 9: structuring only, never a
numeric trading calculation or decision). ``PROMPT_VERSION`` is bumped whenever the prompt text changes -
recorded in ``news_events`` so a later analysis knows which prompt produced which row.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROMPT_VERSION = "v1"

EventType = Literal["regulatory", "macro_policy", "security_hack", "adoption_institutional", "market_structure", "other"]
AssetRelevance = Literal["btc", "crypto_general", "irrelevant"]
DirectionBias = Literal["bullish", "bearish", "neutral"]


class NewsEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    asset_relevance: AssetRelevance
    direction_bias: DirectionBias
    severity: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(max_length=280)


SYSTEM_PROMPT = """You structure cryptocurrency news headlines into a fixed JSON schema for a research \
system. You never predict prices, give trading advice, or compute any numeric indicator - you only \
classify the headline itself, as a human analyst reading just the headline would.

Respond with ONLY a single JSON object (no markdown fences, no commentary) with exactly these fields:
{
  "event_type": one of "regulatory" | "macro_policy" | "security_hack" | "adoption_institutional" | "market_structure" | "other",
  "asset_relevance": one of "btc" | "crypto_general" | "irrelevant",
  "direction_bias": one of "bullish" | "bearish" | "neutral" (your read of the headline's own tone, not a price forecast),
  "severity": a number from 0.0 (routine) to 1.0 (major market-moving event),
  "confidence": a number from 0.0 to 1.0, how confident you are in this classification from the headline alone,
  "summary": a plain-language summary of the headline, at most 280 characters
}"""


def build_user_message(title: str) -> str:
    return f"Headline: {title}"


class NewsEventParseError(Exception):
    pass


def parse_llm_response(text: str) -> NewsEvent:
    """Parse and validate the LLM's raw text against the fixed schema. Tolerates markdown code fences
    (```json ... ```) since models sometimes add them despite being told not to; never guesses a missing
    field or silently coerces an out-of-range value - any failure raises, so the caller stores the raw
    response and the error rather than a fabricated result."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1]
        stripped = stripped[4:] if stripped.lower().startswith("json") else stripped
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise NewsEventParseError(f"not valid JSON: {exc}") from exc
    try:
        return NewsEvent.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError - re-raised as our own type, never swallowed
        raise NewsEventParseError(f"schema validation failed: {exc}") from exc
