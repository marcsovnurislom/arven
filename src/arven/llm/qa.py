"""Stage 10: natural-language Q&A over already-stored data (CLAUDE.md rule 9 / architecture.md section 15).

The LLM answers strictly from the context it is given (``llm.context.build_context``) - it is explicitly
told to say so when the context does not cover a question, and explicitly forbidden from recommending a
future trade or predicting a price: those boundaries are enforced only by the system prompt (there is no
further structural gate here, unlike ``news.schema``'s fixed-schema validation), so this is a weaker
guarantee than the rest of the project's point-in-time/leakage guarantees and is documented as such.
"""

from __future__ import annotations

from arven.llm.anthropic_client import complete

QA_SYSTEM_PROMPT = """You answer questions about a research/decision-support system's own stored history \
(past decisions, paper-trading results, news items) using ONLY the context block you are given below. You \
never use any other information. If the context does not contain the answer, say so plainly rather than \
guessing. You NEVER recommend a trade, predict a future price or market move, or suggest what the system \
should do next - you only describe what the stored data already shows. This is a research tool, not \
financial advice, and you must not imply otherwise."""


def answer_question(question: str, context: str, *, model: str, max_tokens: int = 500, api_key: str | None = None) -> str:
    user_message = f"Context:\n{context}\n\nQuestion: {question}"
    response = complete(QA_SYSTEM_PROMPT, user_message, model=model, max_tokens=max_tokens, api_key=api_key)
    return response.text
