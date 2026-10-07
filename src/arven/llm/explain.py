"""Stage 10: plain-language explanation of one already-made decision (CLAUDE.md rule 9 - the LLM only ever
turns ``reports.decision_summary``'s already-computed fields into prose; it never recomputes, re-scores, or
second-guesses any of them, and it is never given a chance to suggest a *different* action).
"""

from __future__ import annotations

import json

from arven.llm.anthropic_client import complete

EXPLAIN_SYSTEM_PROMPT = """You write a short, plain-language explanation of one trading-system decision for \
a non-technical reader. You are given the decision's own already-computed facts as JSON - you only \
explain *why this decision came out the way it did*, using only those facts. You never suggest what to do \
next, never predict the future, never recommend a trade, and never contradict or second-guess the facts \
given. If the JSON shows the system vetoed or skipped the trade, explain why in plain terms. Keep it to \
2-4 sentences."""


def explain_decision(summary: dict, *, model: str, max_tokens: int = 300, api_key: str | None = None) -> str:
    user_message = f"Decision facts (JSON):\n{json.dumps(summary, sort_keys=True)}"
    response = complete(EXPLAIN_SYSTEM_PROMPT, user_message, model=model, max_tokens=max_tokens, api_key=api_key)
    return response.text
