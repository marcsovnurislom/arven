"""The read-only HTTP API on a temporary data directory: no real database or network is touched."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arven.core.config import load_config
from arven.core.time import to_ms, utc_now
from arven.data.storage.db import connect
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, tp_ladder_from_r_multiples
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.engine.signal_store import append_signal, append_update
from arven.web.app import create_app

HOUR = 3_600_000


@pytest.fixture()
def env(tmp_path: Path):
    base = load_config()
    cfg = base.model_copy(update={"data": base.data.model_copy(update={"data_dir": tmp_path})})
    now = to_ms(utc_now()) // 60_000 * 60_000
    with connect(cfg.data.database_path) as con:
        for i in range(30):
            t = now - (30 - i) * 60_000
            con.execute(
                "INSERT INTO ohlcv_1m (symbol, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume, trade_count, taker_buy_volume, "
                "taker_buy_quote_volume, source_key, ingested_at_ms) VALUES (?, ?, ?, 100, 101, 99, 100.5, 1, 100, 1, 0.5, 50, 'test', 0)", [cfg.market.symbol, t, t + 59_999],
            )
        for i in range(30):
            t = now // HOUR * HOUR - (30 - i) * HOUR
            con.execute(
                "INSERT INTO ohlcv (symbol, timeframe, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume, trade_count, "
                "taker_buy_volume, taker_buy_quote_volume, bar_count, is_complete, built_at_ms) VALUES (?, '1h', ?, ?, 100, 101, 99, ?, 1, 100, 1, 0.5, 50, 60, TRUE, 0)",
                [cfg.market.symbol, t, t + HOUR - 1, 100.0 + i],
            )
    return cfg, TestClient(create_app(cfg, dist_dir=tmp_path / "no-dist")), now


def _signal(strategy_id: str, t: int) -> EngineSignal:
    ladder = tp_ladder_from_r_multiples(((1.0, 0.5), (2.0, 0.5)), entry=100.0, stop=99.0, side=1)
    return EngineSignal(
        symbol="BTCUSDT", side=1, strategy_id=strategy_id, strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=t,
        entry_reference=100.0, stop=99.0, tp_ladder=ladder, risk_fraction=0.01, confidence=0.5, regime="x", reasons=("why",), risk_checks=(),
        versions=SignalVersions("v1", "h", None),
    )


def test_health_and_read_only_surface(env):
    _, client, _ = env
    assert client.get("/api/health").json()["read_only"] is True
    methods = {m for r in client.app.routes for m in getattr(r, "methods", set())}
    paths = {r.path for r in client.app.routes}
    assert not any("order" in p or "trade/" in p for p in paths)
    assert methods <= {"GET", "POST", "DELETE", "HEAD", "OPTIONS"}
    writers = sorted(r.path for r in client.app.routes if "POST" in getattr(r, "methods", set()))
    # only the owner's own journal and review notes (setup labels, trade verdicts) are writable - never an order
    assert writers == ["/api/journal", "/api/s7/labels", "/api/s7/trade_labels"]


def test_overview_reports_fresh_data_and_missing_runtime_honestly(env):
    _, client, now = env
    o = client.get("/api/overview").json()
    assert o["last_1m_bar_open_ms"] == now - 60_000 and o["data_stale"] is False
    assert o["runtime"]["present"] is False and o["runtime"]["stale"] is True
    assert o["signals_total"] == 0 and o["strategies_summary"] is None


def test_candles_ascending_limit_and_validation(env):
    _, client, now = env
    c = client.get("/api/candles", params={"tf": "1m", "limit": 10}).json()["candles"]
    assert len(c) == 10 and [x["t"] for x in c] == sorted(x["t"] for x in c) and c[-1]["t"] == now - 60_000
    h = client.get("/api/candles", params={"tf": "1h", "limit": 5}).json()["candles"]
    assert len(h) == 5 and h[-1]["c"] == 129.0
    older = client.get("/api/candles", params={"tf": "1m", "limit": 5, "before": c[0]["t"]}).json()["candles"]
    assert all(x["t"] < c[0]["t"] for x in older)
    assert client.get("/api/candles", params={"tf": "7m"}).status_code == 422


def test_signals_list_detail_status_and_filters(env):
    cfg, client, now = env
    root = cfg.data.data_dir / "signals"
    s1, s2 = _signal("s6_trend_pullback", now - 2 * HOUR), _signal("s4_impulse_retest", now - HOUR)
    append_signal(root, s1)
    append_signal(root, s2)
    append_update(root, "s6_trend_pullback", SignalUpdate(s1.signal_id, now - HOUR, SignalUpdateKind.TP_HIT, "level=TP1"))
    append_update(root, "s6_trend_pullback", SignalUpdate(s1.signal_id, now - 30 * 60_000, SignalUpdateKind.CLOSED, "reason=STOP"))
    allsig = client.get("/api/signals").json()["signals"]
    assert [s["strategy_id"] for s in allsig] == ["s4_impulse_retest", "s6_trend_pullback"]  # newest first
    by_id = {s["signal_id"]: s for s in allsig}
    assert by_id[s1.signal_id]["status"] == "closed" and len(by_id[s1.signal_id]["updates"]) == 2
    assert by_id[s2.signal_id]["status"] == "open"
    assert [s["signal_id"] for s in client.get("/api/signals", params={"strategy": "s4_impulse_retest"}).json()["signals"]] == [s2.signal_id]
    assert client.get("/api/signals", params={"strategy": "nope"}).json() == {"signals": []}
    assert client.get(f"/api/signals/{s2.signal_id}").json()["reasons"] == ["why"]
    assert client.get("/api/signals/unknown").status_code == 404
    o = client.get("/api/overview").json()
    assert o["signals_total"] == 2 and o["signals_open"] == 1 and o["signals_last_24h"] == 2


def test_strategies_and_research_read_artifacts(env):
    cfg, client, _ = env
    paper = cfg.data.data_dir / "paper"
    (paper / "r1").mkdir(parents=True)
    (paper / "strategies_summary.json").write_text(json.dumps({"strategies": {"s6_trend_pullback": {"signals": 3}}}))
    (paper / "r1" / "run.json").write_text(json.dumps({"run_id": "r1", "created_at": "2026-01-01", "period": "forward", "touched_test_set": False, "metrics": {"total_return": -0.1}}))
    assert client.get("/api/strategies").json()["forward_summary"]["strategies"]["s6_trend_pullback"]["signals"] == 3
    runs = client.get("/api/research").json()["runs"]
    assert runs[0]["run_id"] == "r1" and runs[0]["touched_test_set"] is False and runs[0]["total_return"] == -0.1


def test_screener_lists_every_followed_market_and_only_real_rows(env):
    _, client, _ = env
    s = client.get("/api/screener").json()
    assert s["supported_symbols"] == ["BTCUSDT", "XAUUSDT"]
    assert len(s["rows"]) == 1 and s["rows"][0]["price"] == 129.0 and s["rows"][0]["market"] == "btc"  # no gold bars stored here


def test_journal_add_stats_delete_and_validation(env):
    _, client, _ = env
    assert client.get("/api/journal").json()["entries"] == []
    ok = client.post("/api/journal", json={"symbol": "BTCUSD", "side": 1, "entry": 100, "stop": 98, "exit": 104, "notes": "n", "tags": ["fomo"]})
    assert ok.status_code == 201 and ok.json()["r_multiple"] == pytest.approx(2.0)
    short = client.post("/api/journal", json={"symbol": "BTCUSD", "side": -1, "entry": 100, "stop": 102, "exit": 103}).json()
    assert short["r_multiple"] == pytest.approx(-1.5)
    j = client.get("/api/journal").json()
    assert j["stats"]["trades"] == 2 and j["stats"]["total_r"] == pytest.approx(0.5) and j["stats"]["win_rate"] == pytest.approx(0.5)
    assert client.post("/api/journal", json={"symbol": "X", "side": 2, "entry": 1}).status_code == 422
    assert client.post("/api/journal", json={"symbol": "X", "side": 1, "entry": -1}).status_code == 422
    assert client.delete(f"/api/journal/{short['id']}").status_code == 200
    assert client.delete("/api/journal/missing").status_code == 404
    assert client.get("/api/journal").json()["stats"]["trades"] == 1


def test_telegram_status_never_leaks_secrets(env, monkeypatch):
    _, client, _ = env
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "1,2")
    t = client.get("/api/telegram").json()
    assert t["token_configured"] is True and t["allowed_chats"] == 2 and "SECRET" not in json.dumps(t)


def test_sse_stream_emits_overview_events(env):
    _, client, _ = env
    with client.stream("GET", "/api/stream", params={"interval": 0.2, "max_events": 2}) as r:
        body = "".join(r.iter_text())
    events = [ln for ln in body.splitlines() if ln.startswith("event: overview")]
    assert len(events) == 2 and "data: " in body


def test_cors_allows_only_localhost_origins(env):
    _, client, _ = env
    good = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    bad = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert good.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_built_frontend_is_served_from_dist_when_present(env, tmp_path):
    cfg, _, _ = env
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>ARVEN</title>", encoding="utf-8")
    client = TestClient(create_app(cfg, dist_dir=dist))
    assert "ARVEN" in client.get("/").text
    assert client.get("/api/health").json()["status"] == "ok"  # API routes still win over the static mount


def test_s7_review_returns_the_export_and_stores_owner_labels(env):
    cfg, client, _ = env
    assert client.get("/api/s7/review").json()["setups"] == []
    review = cfg.data.data_dir / "s7_review"
    review.mkdir(parents=True)
    (review / "setups_1h.json").write_text(json.dumps({"timeframe": "1h", "total_setups": 1, "setups": [{"id": "1h-1000-L"}]}))
    assert client.get("/api/s7/review", params={"tf": "1h"}).json()["setups"][0]["id"] == "1h-1000-L"
    assert client.get("/api/s7/review", params={"tf": "2h"}).status_code == 422
    ok = client.post("/api/s7/labels", json={"setup_id": "1h-1000-L", "verdict": "yes", "note": "clean break"})
    assert ok.status_code == 200 and ok.json()["count"] == 1
    assert client.get("/api/s7/labels").json()["labels"]["1h-1000-L"]["verdict"] == "yes"
    assert client.post("/api/s7/labels", json={"setup_id": "1h-1000-L", "verdict": "maybe"}).status_code == 422
    assert client.post("/api/s7/labels", json={"setup_id": "../../etc", "verdict": "yes"}).status_code == 422


def test_s7_review_of_gold_has_its_own_setups_and_labels(env):
    cfg, client, _ = env
    gold = cfg.data.data_dir / "markets" / "XAUUSD" / "s7_review"
    gold.mkdir(parents=True)
    (gold / "setups_1h.json").write_text(json.dumps({"timeframe": "1h", "total_setups": 1, "setups": [{"id": "1h-2000-S"}]}))
    assert client.get("/api/s7/review", params={"market": "gold"}).json()["setups"][0]["id"] == "1h-2000-S"
    assert client.get("/api/s7/review").json()["setups"] == []  # BTC has no export in this fixture
    assert client.post("/api/s7/labels", params={"market": "gold"}, json={"setup_id": "1h-2000-S", "verdict": "no", "note": ""}).status_code == 200
    assert client.get("/api/s7/labels", params={"market": "gold"}).json()["labels"]["1h-2000-S"]["verdict"] == "no"
    assert client.get("/api/s7/labels").json()["labels"] == {}  # BTC's labels untouched
    assert not (cfg.data.data_dir / "s7_review").exists()


def test_s7_trades_serves_the_study_export_read_only(env):
    cfg, client, _ = env
    assert client.get("/api/s7/trades").json() == {"period": "development", "trades": [], "summary": None}
    study = cfg.data.data_dir / "s7_study"
    study.mkdir(parents=True)
    (study / "trades_validation.json").write_text(json.dumps({"period": "validation", "summary": {"trades": 1}, "trades": [{"n": 1}]}))
    assert client.get("/api/s7/trades", params={"period": "validation"}).json()["trades"] == [{"n": 1}]
    assert client.get("/api/s7/trades", params={"period": "test"}).status_code == 422  # the sealed test is never served


def test_s7_trade_labels_store_the_owners_verdicts(env):
    _, client, _ = env
    assert client.get("/api/s7/trade_labels").json() == {"labels": {}}
    ok = client.post("/api/s7/trade_labels", json={"trade_id": "15m-1690000000000-S", "verdict": "wrong", "note": "entry too early"})
    assert ok.status_code == 200 and ok.json()["count"] == 1
    got = client.get("/api/s7/trade_labels").json()["labels"]["15m-1690000000000-S"]
    assert got["verdict"] == "wrong" and got["note"] == "entry too early"
    assert client.post("/api/s7/trade_labels", json={"trade_id": "15m-1-S", "verdict": "maybe"}).status_code == 422
    assert client.post("/api/s7/trade_labels", json={"trade_id": "../x", "verdict": "ok"}).status_code == 422


def test_strategy_trades_index_and_files_read_only(env):
    cfg, client, _ = env
    assert client.get("/api/strategy_trades/index").json() == {"entries": []}
    root = cfg.data.data_dir / "strategy_trades"
    (root / "s6_trend_pullback").mkdir(parents=True)
    (root / "index.json").write_text(json.dumps([{"strategy": "s6_trend_pullback", "period": "forward"}]))
    (root / "s6_trend_pullback" / "forward.json").write_text(json.dumps({"strategy": "s6_trend_pullback", "trades": [{"n": 1}], "summary": {}}))
    assert client.get("/api/strategy_trades/index").json()["entries"][0]["period"] == "forward"
    assert client.get("/api/strategy_trades", params={"strategy": "s6_trend_pullback", "period": "forward"}).json()["trades"] == [{"n": 1}]
    assert client.get("/api/strategy_trades", params={"strategy": "../etc", "period": "forward"}).status_code == 422
    assert client.get("/api/strategy_trades", params={"strategy": "s6_trend_pullback", "period": "x"}).status_code == 422


def test_markets_btc_and_gold_are_listed_and_unknown_is_404(env):
    _, client, _ = env
    m = client.get("/api/markets").json()
    ids = [x["id"] for x in m["markets"]]
    assert ids[0] == "btc" and "gold" in ids and m["default"] == "btc"
    gold = next(x for x in m["markets"] if x["id"] == "gold")
    assert gold["symbol"] == "XAUUSDT" and gold["history_symbol"] == "XAUUSD" and gold["session"] == "cme_metals"
    assert client.get("/api/overview", params={"market": "nope"}).status_code == 404
    assert client.get("/api/overview", params={"market": "BAD!"}).status_code == 422


def test_gold_reads_its_own_record_and_charts_continue_into_the_history(env):
    cfg, client, now = env
    gold_signals = cfg.data.data_dir / "markets" / "XAUUSDT" / "signals"
    s = _signal("s4_impulse_retest", now - HOUR)
    append_signal(gold_signals, s)
    got = client.get("/api/signals", params={"market": "gold"}).json()["signals"]
    assert len(got) == 1 and got[0]["strategy_id"] == "s4_impulse_retest"
    assert client.get("/api/signals").json()["signals"] == []  # the BTC record is separate
    assert client.get("/api/strategies", params={"market": "gold"}).json()["strategies"] == ["s4_impulse_retest"]
    with connect(cfg.data.database_path) as con:
        for i in range(5):
            t = now - (1000 - i) * 60_000
            con.execute(
                "INSERT INTO ohlcv_1m (symbol, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume, trade_count, taker_buy_volume, "
                "taker_buy_quote_volume, source_key, ingested_at_ms) VALUES ('XAUUSD', ?, ?, 2000, 2001, 1999, 2000.5, 1, 2000, 0, 0, 0, 'duka', 0)", [t, t + 59_999],
            )
    c = client.get("/api/candles", params={"tf": "1m", "limit": 3, "market": "gold"}).json()
    assert c["source"] == "XAUUSD" and len(c["candles"]) == 3 and c["candles"][-1]["c"] == 2000.5  # no XAUUSDT bars yet
    o = client.get("/api/overview", params={"market": "gold"}).json()
    assert o["market"] == "gold" and o["symbol"] == "XAUUSDT" and o["last_1m_bar_open_ms"] is None and o["data_stale"] is True
    with connect(cfg.data.database_path) as con:
        for i in range(3):
            t = now // HOUR * HOUR - (3 - i) * HOUR
            con.execute(
                "INSERT INTO ohlcv (symbol, timeframe, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume, trade_count, "
                "taker_buy_volume, taker_buy_quote_volume, bar_count, is_complete, built_at_ms) VALUES ('XAUUSD', '1h', ?, ?, 2000, 2001, 1999, ?, 1, 2000, 0, 0, 0, 60, TRUE, 0)",
                [t, t + HOUR - 1, 2000.0 + i],
            )
    s2 = client.get("/api/screener").json()
    assert [r["market"] for r in s2["rows"]] == ["btc", "gold"]
    assert s2["rows"][1]["symbol"] == "XAUUSD" and s2["rows"][1]["price"] == 2002.0  # history until the live feed has bars


def test_sessions_report_every_market_from_its_own_calendar_and_the_centres(env):
    cfg, client, _ = env
    r = client.get("/api/sessions").json()
    by_id = {m["id"]: m for m in r["markets"]}
    assert by_id["btc"]["state"] == "always_open" and by_id["btc"]["next_holiday"] is None
    gold = by_id["gold"]
    gold_cal = load_config(instrument="XAUUSDT").session_calendar()
    assert gold["session"] == "cme_metals" and gold["open"] == bool(gold_cal.is_open(r["now_ms"] // 60_000 * 60_000))
    assert gold["next_change_ms"] > r["now_ms"]
    assert [c["id"] for c in r["centres"]] == ["sydney", "tokyo", "london", "new_york"]
    assert all(c["next_change_ms"] > r["now_ms"] for c in r["centres"])


def test_activity_grid_from_stored_hourly_bars(env):
    _, client, _ = env
    a = client.get("/api/activity").json()
    assert a["source"] == "BTCUSDT" and a["bars"] == 30 and sum(map(sum, a["n"])) == 30
    values = [v for row in a["mean_range_pct"] for v in row if v is not None]
    assert values and all(v == 2.0 for v in values)  # every fixture bar: (101 - 99) / 100
    g = client.get("/api/activity", params={"market": "gold"}).json()
    assert g["bars"] == 0 and all(v is None for row in g["mean_range_pct"] for v in row)
    assert client.get("/api/activity", params={"days": 3}).status_code == 422


def test_events_lists_the_next_releases_and_a_summary_per_type(env):
    _, client, now = env
    e = client.get("/api/events").json()
    assert e["market"] == "btc" and e["horizons_min"] == [15, 60, 240]
    assert all(x["time_ms"] > e["now_ms"] for x in e["upcoming"]) and set(e["known_until"]) == {"FOMC", "CPI", "NFP"}
    assert set(e["summary"]) == {"FOMC", "CPI", "NFP"}  # the fixture has no 15m bars: every type measured 0 times
    assert e["measured"] == 0 and all(v == {"n": 0} for per in e["summary"].values() for v in per.values())
    assert client.get("/api/events", params={"market": "gold"}).json()["market"] == "gold"
