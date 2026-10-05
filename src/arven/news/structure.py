"""Turn one raw news item into a structured result by calling the LLM once and validating its response
against the fixed schema. Never raises on a malformed LLM response - that is a normal, expected outcome
(models occasionally fail to follow the format), recorded honestly (``parse_error`` set, ``event=None``),
not retried indefinitely and not silently discarded.
"""

from __future__ import annotations

from dataclasses import dataclass

from arven.llm.anthropic_client import LLMResponse, complete
from arven.news.schema import PROMPT_VERSION, SYSTEM_PROMPT, NewsEvent, NewsEventParseError, build_user_message, parse_llm_response


@dataclass(frozen=True, slots=True)
class StructuredResult:
    news_id: str
    llm_model: str
    prompt_version: str
    event: NewsEvent | None
    raw_response: str
    parse_error: str | None
    input_tokens: int
    output_tokens: int


def structure_item(news_id: str, title: str, *, llm_model: str, max_tokens: int, api_key: str | None = None) -> StructuredResult:
    response: LLMResponse = complete(SYSTEM_PROMPT, build_user_message(title), model=llm_model, max_tokens=max_tokens, api_key=api_key)
    try:
        event = parse_llm_response(response.text)
        return StructuredResult(news_id, llm_model, PROMPT_VERSION, event, response.text, None, response.input_tokens, response.output_tokens)
    except NewsEventParseError as exc:
        return StructuredResult(news_id, llm_model, PROMPT_VERSION, None, response.text, str(exc), response.input_tokens, response.output_tokens)
