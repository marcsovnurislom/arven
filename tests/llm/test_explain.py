"""Stage 10: explain_decision() turns an already-computed decision summary into prose, offline (fake LLM)."""

from __future__ import annotations

import json

import arven.llm.explain as explain_mod
from arven.llm.anthropic_client import LLMResponse
from arven.llm.explain import explain_decision

SUMMARY = {
    "t_ms": 0, "regime": "TREND_UP/NORMAL", "candidates": [], "proposed_action": "NO_TRADE",
    "proposed_score": 0.0, "proposed_confidence": 0.0, "contributing": [], "gated_out": [],
    "reasons": [], "ml_filtered": False, "risk_outcome": "no_proposal", "risk_reason": "x", "risk_detail": {},
}


def test_explain_decision_sends_the_summary_as_json_and_returns_the_llm_text(monkeypatch):
    seen = {}

    def fake(system, user_message, *, model, max_tokens=512, api_key=None, **_):
        seen["system"] = system
        seen["user_message"] = user_message
        seen["model"] = model
        seen["max_tokens"] = max_tokens
        return LLMResponse("plain-language explanation", model, 5, 5)

    monkeypatch.setattr(explain_mod, "complete", fake)

    text = explain_decision(SUMMARY, model="m", max_tokens=123)

    assert text == "plain-language explanation"
    assert seen["model"] == "m" and seen["max_tokens"] == 123
    assert json.dumps(SUMMARY, sort_keys=True) in seen["user_message"]
    assert "never" in seen["system"].lower()  # the never-recommend/never-predict guardrail is present
