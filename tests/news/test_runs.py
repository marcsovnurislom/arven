"""Stage 9b composition root: fetch -> store -> structure, end to end, offline (fake RSS + fake LLM)."""

from __future__ import annotations

import io
import json

import arven.news.structure as structure_mod
from arven.core.config import load_config
from arven.core.news_config import NewsConfig
from arven.core.time import from_ms, to_ms
from arven.data.download import Downloader, RetryPolicy
from arven.data.storage.db import connect
from arven.llm.anthropic_client import LLMResponse
from arven.news.runs import run_news_tick
from test_rss import ITEM, feed

APP = load_config()


def news_cfg(**overrides) -> NewsConfig:
    base = {"feeds": {"fake": "http://fake/rss"}, "llm_model": "m", "max_items_per_tick": 10, "max_tokens": 512}
    return NewsConfig.model_validate({**base, **overrides})


def rss_downloader(body: bytes) -> Downloader:
    class FakeRssOpener:
        def __call__(self, request, timeout):
            resp = io.BytesIO(body)
            resp.headers = {"Content-Length": str(len(body))}
            return resp

    return Downloader(RetryPolicy.from_config(APP.download), opener=FakeRssOpener(), sleep=lambda s: None)


GOOD_EVENT = json.dumps({
    "event_type": "regulatory", "asset_relevance": "btc", "direction_bias": "bullish",
    "severity": 0.5, "confidence": 0.8, "summary": "ok",
})


def _fake_complete(monkeypatch, *texts: str) -> None:
    """Patch arven.news.structure's own bound name for `complete` (it imports the function directly, so
    patching the origin module after that import would not be observed here)."""
    calls = {"i": 0}

    def fake(system, user_message, *, model, max_tokens=512, api_key=None, **_):
        text = texts[calls["i"]]
        calls["i"] += 1
        return LLMResponse(text, model, 5, 5)

    monkeypatch.setattr(structure_mod, "complete", fake)


def test_fetches_and_stores_new_items(monkeypatch):
    xml = feed(ITEM.format(title="a", link="http://x/a", pubdate="Sun, 04 Oct 2026 22:31:12 +0000"))
    con = connect(":memory:")
    _fake_complete(monkeypatch, GOOD_EVENT)
    summary = run_news_tick(APP, news_cfg(), con, downloader=rss_downloader(xml), api_key="k")
    assert summary.ok and summary.items_fetched == 1 and summary.items_new == 1
    assert summary.items_structured == 1
    row = con.execute("SELECT title, source FROM news_items").fetchone()
    assert row == ("a", "fake")


def test_second_tick_does_not_refetch_or_restructure_the_same_item(monkeypatch):
    xml = feed(ITEM.format(title="a", link="http://x/a", pubdate="Sun, 04 Oct 2026 22:31:12 +0000"))
    con = connect(":memory:")
    _fake_complete(monkeypatch, GOOD_EVENT)
    s1 = run_news_tick(APP, news_cfg(), con, downloader=rss_downloader(xml), api_key="k")
    _fake_complete(monkeypatch, GOOD_EVENT)  # would fail if actually called again (index out of range)
    s2 = run_news_tick(APP, news_cfg(), con, downloader=rss_downloader(xml), api_key="k")
    assert s1.items_new == 1 and s2.items_new == 0
    assert s1.items_structured == 1 and s2.items_structured == 0
    assert con.execute("SELECT count(*) FROM news_items").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM news_events").fetchone()[0] == 1


def test_max_items_per_tick_caps_llm_calls_cost_control(monkeypatch):
    items = [ITEM.format(title=f"t{i}", link=f"http://x/{i}", pubdate="Sun, 04 Oct 2026 22:31:12 +0000") for i in range(5)]
    xml = feed(*items)
    con = connect(":memory:")
    _fake_complete(monkeypatch, GOOD_EVENT, GOOD_EVENT)  # only 2 scripted - a 3rd call would raise IndexError
    summary = run_news_tick(APP, news_cfg(max_items_per_tick=2), con, downloader=rss_downloader(xml), api_key="k")
    assert summary.items_new == 5 and summary.items_structured == 2
    assert con.execute("SELECT count(*) FROM news_events").fetchone()[0] == 2


def test_a_malformed_llm_response_is_recorded_not_silently_dropped(monkeypatch):
    xml = feed(ITEM.format(title="a", link="http://x/a", pubdate="Sun, 04 Oct 2026 22:31:12 +0000"))
    con = connect(":memory:")
    _fake_complete(monkeypatch, "not json at all")
    summary = run_news_tick(APP, news_cfg(), con, downloader=rss_downloader(xml), api_key="k")
    assert summary.items_parse_failed == 1 and summary.items_structured == 0
    row = con.execute("SELECT event_type, parse_error, raw_response FROM news_events").fetchone()
    assert row[0] is None and row[1] is not None and row[2] == "not json at all"


def test_available_at_is_never_earlier_than_ingestion_time(monkeypatch):
    old_pubdate = "Sun, 04 Oct 2020 22:31:12 +0000"  # a news item published years ago, "ingested" now
    xml = feed(ITEM.format(title="old", link="http://x/old", pubdate=old_pubdate))
    con = connect(":memory:")
    _fake_complete(monkeypatch, GOOD_EVENT)
    now_ms = to_ms(load_config().data.history_end)  # any fixed instant well after old_pubdate
    run_news_tick(APP, news_cfg(), con, downloader=rss_downloader(xml), api_key="k", now=from_ms(now_ms))
    published_ms, available_ms = con.execute("SELECT published_at_ms, available_at_ms FROM news_items").fetchone()
    assert available_ms == now_ms and available_ms > published_ms
