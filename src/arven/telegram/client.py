"""Minimal Telegram Bot API client (stdlib HTTP only - no SDK, the same choice already made for Binance
REST (``data.adapters.binance_rest``) and the Anthropic API (``llm.anthropic_client``)).

The bot token is never hardcoded or committed: read from ``TELEGRAM_BOT_TOKEN`` (environment / ``.env``,
CLAUDE.md: "Secrets only via environment variables / .env, git-ignored").
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

API_BASE = "https://api.telegram.org/bot"
USER_AGENT = "arven-research/0.1 (+paper-signal alerts, Phase 6)"


class TelegramConfigError(Exception):
    """No bot token configured - never silently skipped."""


class TelegramRequestError(Exception):
    """The API call failed after retries, or returned a non-retryable error."""


@dataclass(frozen=True, slots=True)
class SentMessage:
    message_id: int
    chat_id: str


@dataclass(frozen=True, slots=True)
class Update:
    update_id: int
    chat_id: str
    text: str
    date_ms: int


def _bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramConfigError(
            "TELEGRAM_BOT_TOKEN is not set (environment variable or .env). There is no fallback, since "
            "silently skipping a send would misreport what happened."
        )
    return token


def _call(
    method: str, params: dict[str, object], *, token: str, max_attempts: int, opener, sleep,
) -> dict:
    """One Bot API call, retried on transient failure and on HTTP 429 (waiting exactly
    ``retry_after`` seconds, Telegram's own rate-limit contract - section 5.4's "respect 429 retry_after")."""
    url = f"{API_BASE}{token}/{method}"
    body = json.dumps(params).encode()
    headers = {"content-type": "application/json", "User-Agent": USER_AGENT}
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with opener(request, timeout=35) as resp:
                payload = json.loads(resp.read())
            if payload.get("ok"):
                return payload["result"]
            raise TelegramRequestError(f"{method} failed: {payload.get('description')!r}")
        except urllib.error.HTTPError as exc:
            detail = json.loads(exc.read() or b"{}")
            if exc.code == 429:
                retry_after = float(detail.get("parameters", {}).get("retry_after", 1.0))
                if attempt < max_attempts:
                    sleep(retry_after)
                last_error = TelegramRequestError(f"429 rate-limited, retry_after={retry_after}")
                continue
            if exc.code in (401, 403):
                raise TelegramRequestError(f"authentication/authorization failed (HTTP {exc.code}) - check TELEGRAM_BOT_TOKEN") from exc
            if exc.code == 400:
                raise TelegramRequestError(f"bad request (HTTP 400): {detail.get('description')!r}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < max_attempts:
            sleep(min(2.0 ** attempt, 10.0))
    raise TelegramRequestError(f"giving up on {method} after {max_attempts} attempts: {last_error!r}")


def send_message(
    chat_id: str, text: str, *, token: str | None = None, max_attempts: int = 5,
    opener=urllib.request.urlopen, sleep=time.sleep,
) -> SentMessage:
    result = _call(
        "sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        token=token or _bot_token(), max_attempts=max_attempts, opener=opener, sleep=sleep,
    )
    return SentMessage(result["message_id"], chat_id)


def edit_message_text(
    chat_id: str, message_id: int, text: str, *, token: str | None = None, max_attempts: int = 5,
    opener=urllib.request.urlopen, sleep=time.sleep,
) -> None:
    _call(
        "editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text},
        token=token or _bot_token(), max_attempts=max_attempts, opener=opener, sleep=sleep,
    )


def get_updates(
    offset: int, *, timeout_seconds: int = 0, token: str | None = None, max_attempts: int = 3,
    opener=urllib.request.urlopen, sleep=time.sleep,
) -> list[Update]:
    """Long-poll for new incoming messages (bot commands) since ``offset`` (exclusive - pass
    ``last_update_id + 1``; ``0`` on the very first call)."""
    result = _call(
        "getUpdates", {"offset": offset, "timeout": timeout_seconds, "allowed_updates": ["message"]},
        token=token or _bot_token(), max_attempts=max_attempts, opener=opener, sleep=sleep,
    )
    updates = []
    for item in result:
        msg = item.get("message")
        if not msg or "text" not in msg:
            continue
        updates.append(Update(item["update_id"], str(msg["chat"]["id"]), msg["text"], msg["date"] * 1000))
    return updates
