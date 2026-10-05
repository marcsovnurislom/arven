"""NewsEvent schema validation: valid/invalid LLM output, markdown-fence tolerance, no silent coercion."""

from __future__ import annotations

import json

import pytest

from arven.news.schema import NewsEvent, NewsEventParseError, parse_llm_response

VALID = {
    "event_type": "regulatory", "asset_relevance": "btc", "direction_bias": "bullish",
    "severity": 0.7, "confidence": 0.9, "summary": "A regulator said something.",
}


def test_parses_a_well_formed_response():
    event = parse_llm_response(json.dumps(VALID))
    assert isinstance(event, NewsEvent)
    assert event.event_type == "regulatory" and event.severity == 0.7


def test_tolerates_markdown_code_fences():
    text = "```json\n" + json.dumps(VALID) + "\n```"
    assert parse_llm_response(text).event_type == "regulatory"


def test_tolerates_bare_fences_without_the_json_language_tag():
    text = "```\n" + json.dumps(VALID) + "\n```"
    assert parse_llm_response(text).event_type == "regulatory"


def test_not_json_at_all_raises_not_a_crash_or_silent_default():
    with pytest.raises(NewsEventParseError, match="not valid JSON"):
        parse_llm_response("I think this news is bullish for Bitcoin.")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(event_type="made_up_category"),
        lambda d: d.update(severity=1.5),
        lambda d: d.update(severity=-0.1),
        lambda d: d.update(confidence="high"),
        lambda d: d.pop("summary"),
        lambda d: d.update(extra_field="not allowed"),
        lambda d: d.update(summary="x" * 281),
    ],
)
def test_schema_violations_raise_never_silently_coerced(mutate):
    d = dict(VALID)
    mutate(d)
    with pytest.raises(NewsEventParseError, match="schema validation failed"):
        parse_llm_response(json.dumps(d))


def test_extra_whitespace_around_the_json_is_tolerated():
    assert parse_llm_response("  \n" + json.dumps(VALID) + "\n  ").event_type == "regulatory"
