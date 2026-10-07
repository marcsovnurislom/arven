"""Telegram Bot API client: response parsing, retry/429/auth behaviour - offline (scripted opener, no
sockets), mirroring tests/llm/test_anthropic_client.py's pattern."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from arven.telegram.client import TelegramConfigError, TelegramRequestError, edit_message_text, get_updates, send_message


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code: int, body: dict | None = None) -> urllib.error.HTTPError:
    payload = json.dumps(body or {"ok": False, "error_code": code, "description": "err"}).encode()
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(payload))


class ScriptedOpener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[object] = []

    def __call__(self, request, timeout):
        self.calls.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def ok_response(result) -> FakeResponse:
    return FakeResponse(json.dumps({"ok": True, "result": result}).encode())


# --- send_message ------------------------------------------------------------------------------------


def test_send_message_returns_the_message_id():
    opener = ScriptedOpener(ok_response({"message_id": 42, "chat": {"id": 1}}))
    sent = send_message("123", "hello", token="t", opener=opener, sleep=lambda s: None)
    assert sent.message_id == 42 and sent.chat_id == "123"
    body = json.loads(opener.calls[0].data)
    assert body == {"chat_id": "123", "text": "hello", "disable_web_page_preview": True}


def test_retries_a_5xx_then_succeeds():
    opener = ScriptedOpener(http_error(502), ok_response({"message_id": 1}))
    sent = send_message("1", "x", token="t", opener=opener, sleep=lambda s: None)
    assert sent.message_id == 1 and len(opener.calls) == 2


def test_401_is_not_retried():
    opener = ScriptedOpener(http_error(401))
    with pytest.raises(TelegramRequestError, match="authentication"):
        send_message("1", "x", token="bad", opener=opener, sleep=lambda s: None)
    assert len(opener.calls) == 1


def test_gives_up_after_max_attempts():
    opener = ScriptedOpener(http_error(500), http_error(500), http_error(500))
    with pytest.raises(TelegramRequestError, match="giving up"):
        send_message("1", "x", token="t", max_attempts=3, opener=opener, sleep=lambda s: None)


def test_429_waits_exactly_retry_after_then_retries():
    opener = ScriptedOpener(http_error(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}), ok_response({"message_id": 9}))
    slept = []
    sent = send_message("1", "x", token="t", opener=opener, sleep=slept.append)
    assert sent.message_id == 9
    assert slept == [7.0]  # waited exactly retry_after, not a generic backoff


def test_logical_ok_false_without_an_http_error_raises():
    opener = ScriptedOpener(FakeResponse(json.dumps({"ok": False, "description": "chat not found"}).encode()))
    with pytest.raises(TelegramRequestError, match="chat not found"):
        send_message("1", "x", token="t", opener=opener, sleep=lambda s: None)


def test_missing_bot_token_raises_a_clear_config_error(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    opener = ScriptedOpener(ok_response({"message_id": 1}))
    with pytest.raises(TelegramConfigError):
        send_message("1", "x", opener=opener, sleep=lambda s: None)
    assert opener.calls == []  # never even attempted a request without a token


# --- edit_message_text --------------------------------------------------------------------------------


def test_edit_message_text_sends_the_right_params():
    opener = ScriptedOpener(ok_response({"message_id": 5}))
    edit_message_text("1", 5, "new text", token="t", opener=opener, sleep=lambda s: None)
    body = json.loads(opener.calls[0].data)
    assert body == {"chat_id": "1", "message_id": 5, "text": "new text"}


# --- get_updates ---------------------------------------------------------------------------------------


def test_get_updates_parses_messages_and_skips_non_message_updates():
    opener = ScriptedOpener(ok_response([
        {"update_id": 100, "message": {"message_id": 1, "chat": {"id": 7}, "text": "/status", "date": 1_700_000_000}},
        {"update_id": 101, "edited_message": {"message_id": 1, "chat": {"id": 7}, "text": "edited"}},  # no "message" key
    ]))
    updates = get_updates(0, token="t", opener=opener, sleep=lambda s: None)
    assert len(updates) == 1
    u = updates[0]
    assert u.update_id == 100 and u.chat_id == "7" and u.text == "/status" and u.date_ms == 1_700_000_000_000


def test_get_updates_sends_the_offset_and_timeout():
    opener = ScriptedOpener(ok_response([]))
    get_updates(55, timeout_seconds=20, token="t", opener=opener, sleep=lambda s: None)
    body = json.loads(opener.calls[0].data)
    assert body["offset"] == 55 and body["timeout"] == 20
