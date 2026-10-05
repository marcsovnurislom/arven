"""Minimal Anthropic Messages API client (stdlib HTTP only - no ``anthropic`` SDK dependency, mirroring the
project's existing preference for a thin, dependency-free client over a full SDK; see
``data.adapters.binance_rest`` for the same choice made for market data).

The API key is never hardcoded or committed: it is read from the ``ANTHROPIC_API_KEY`` environment
variable (CLAUDE.md: "Secrets only via environment variables / .env, git-ignored"), optionally loaded from
a local ``.env`` file via ``python-dotenv`` (already a project dependency).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
USER_AGENT = "arven-research/0.1 (+news structuring, Stage 9b)"


class AnthropicConfigError(Exception):
    """No API key configured - never silently skipped, never a trading-relevant default."""


class AnthropicRequestError(Exception):
    """The API call failed after retries, or returned a non-retryable error."""


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AnthropicConfigError(
            "ANTHROPIC_API_KEY is not set (environment variable or .env). Stage 9b news structuring "
            "requires it - there is no fallback, since silently skipping would misreport what ran."
        )
    return key


def complete(
    system: str, user_message: str, *, model: str, max_tokens: int = 512, max_attempts: int = 3,
    api_key: str | None = None, opener=urllib.request.urlopen, sleep=time.sleep,
) -> LLMResponse:
    """One Messages API call, no streaming, no tool use - a single structured-extraction turn."""
    key = api_key or _api_key()
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }).encode()
    headers = {
        "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json", "User-Agent": USER_AGENT,
    }
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
        try:
            with opener(request, timeout=30) as resp:
                payload = json.loads(resp.read())
            text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
            usage = payload.get("usage", {})
            return LLMResponse(text, payload.get("model", model), usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AnthropicRequestError(f"authentication failed (HTTP {exc.code}) - check ANTHROPIC_API_KEY") from exc
            if exc.code == 400:
                raise AnthropicRequestError(f"bad request (HTTP 400): {exc.read()[:500]!r}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < max_attempts:
            sleep(min(2.0 ** attempt, 10.0))
    raise AnthropicRequestError(f"giving up after {max_attempts} attempts: {last_error!r}")
