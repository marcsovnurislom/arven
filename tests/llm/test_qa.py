"""Stage 10: answer_question() turns a context block + question into an LLM answer, offline (fake LLM)."""

from __future__ import annotations

import arven.llm.qa as qa_mod
from arven.llm.anthropic_client import LLMResponse
from arven.llm.qa import answer_question


def test_answer_question_sends_context_and_question_and_returns_the_llm_text(monkeypatch):
    seen = {}

    def fake(system, user_message, *, model, max_tokens=512, api_key=None, **_):
        seen["system"] = system
        seen["user_message"] = user_message
        return LLMResponse("the answer", model, 5, 5)

    monkeypatch.setattr(qa_mod, "complete", fake)

    answer = answer_question("how many trades?", "Latest paper run: run-1\nMetrics: {}", model="m")

    assert answer == "the answer"
    assert "Latest paper run: run-1" in seen["user_message"]
    assert "how many trades?" in seen["user_message"]
    assert "never recommend a trade" in seen["system"].lower()
