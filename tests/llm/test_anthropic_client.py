"""Anthropic Messages API client: response parsing, retry behaviour, and the no-silent-default API-key
guarantee - offline (scripted opener, no sockets)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from arven.llm.anthropic_client import AnthropicConfigError, AnthropicRequestError, complete


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


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


def message_response(text: str, model="claude-haiku-4-5-20251001", in_tok=10, out_tok=20) -> FakeResponse:
    body = json.dumps({
        "content": [{"type": "text", "text": text}], "model": model,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    }).encode()
    return FakeResponse(body)


def test_complete_parses_text_and_usage():
    opener = ScriptedOpener(message_response("hello"))
    r = complete("sys", "user", model="m", opener=opener, api_key="k", sleep=lambda s: None)
    assert r.text == "hello" and r.input_tokens == 10 and r.output_tokens == 20
    sent = json.loads(opener.calls[0].data)
    assert sent["system"] == "sys" and sent["messages"] == [{"role": "user", "content": "user"}]
    assert opener.calls[0].headers["X-api-key"] == "k"  # urllib title-cases header names


def test_retries_a_5xx_then_succeeds():
    opener = ScriptedOpener(http_error(503), message_response("ok"))
    r = complete("s", "u", model="m", opener=opener, api_key="k", max_attempts=3, sleep=lambda s: None)
    assert r.text == "ok" and len(opener.calls) == 2


def test_401_is_not_retried():
    opener = ScriptedOpener(http_error(401))
    with pytest.raises(AnthropicRequestError, match="authentication"):
        complete("s", "u", model="m", opener=opener, api_key="bad", sleep=lambda s: None)
    assert len(opener.calls) == 1


def test_gives_up_after_max_attempts():
    opener = ScriptedOpener(http_error(503), http_error(503), http_error(503))
    with pytest.raises(AnthropicRequestError, match="giving up"):
        complete("s", "u", model="m", opener=opener, api_key="k", max_attempts=3, sleep=lambda s: None)


def test_missing_api_key_raises_a_clear_config_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    opener = ScriptedOpener(message_response("unused"))
    with pytest.raises(AnthropicConfigError):
        complete("s", "u", model="m", opener=opener, sleep=lambda s: None)  # no api_key override either
    assert opener.calls == []  # never even attempted a request without a key


def test_multiple_text_blocks_are_concatenated():
    body = json.dumps({
        "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
        "model": "m", "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()
    opener = ScriptedOpener(FakeResponse(body))
    r = complete("s", "u", model="m", opener=opener, api_key="k", sleep=lambda s: None)
    assert r.text == "ab"
