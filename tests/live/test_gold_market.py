"""A second market (gold) in the live process: its own signal record, closed-market handling (no stale alarm on a
weekend, but stale when it should be trading), the loop's per-market state, Telegram labels and backups. Offline."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from bt_helpers import bulk_insert_1m
from rest_helpers import FakeBinanceRestOpener
from test_live_service import Fake

from arven.core.config import DEFAULT_CONFIG_DIR, load_config
from arven.core.features_config import load_features_config
from arven.core.live_config import LiveConfig, LiveMarketConfig, LiveStrategyConfig, load_live_config
from arven.core.time import UTC, from_ms, to_ms
from arven.data.download import Downloader, RetryPolicy
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.storage.db import connect
from arven.engine.signal_store import read_signals
from arven.live.loop import LoopDeps, LoopState, poll_once
from arven.live.service import LiveTickOutcome, run_live_tick

MIN = 60_000


def ms(*a) -> int:
    return to_ms(datetime(*a, tzinfo=UTC))


MON = ms(2024, 7, 8)  # a Monday, New York summer time
FRIDAY_CLOSE = ms(2024, 7, 12, 21)  # 17:00 New York


@pytest.fixture
def gold_env(tmp_path):
    d = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, d)
    default = yaml.safe_load((d / "default.yaml").read_text(encoding="utf-8"))
    default["data"]["data_dir"] = str(tmp_path / "data")
    default["data"]["history_start"] = "2024-07-01"
    (d / "default.yaml").write_text(yaml.safe_dump(default), encoding="utf-8")
    (d / "splits.yaml").write_text(yaml.safe_dump({
        "development": {"start": "2024-07-01", "end": "2024-07-02"}, "validation": {"start": "2024-07-02", "end": "2024-07-03"},
        "test": {"start": "2024-07-03", "end": "2024-07-04", "sealed": True}, "forward_start": "2024-07-10"}), encoding="utf-8")
    app = load_config(d, instrument="XAUUSDT")
    cal = app.session_calendar()
    minutes = cal.open_minutes(MON - 2 * 86_400_000, FRIDAY_CLOSE)
    rng = np.random.default_rng(4)
    px = 2400 + np.cumsum(rng.normal(0, 0.3, len(minutes)))
    con = connect(app.data.database_path)
    bulk_insert_1m(con, [("XAUUSDT", int(t), int(t) + MIN, p, p + 0.2, p - 0.2, p, 1.0, p, 3, 0.5, 0.5 * p, "seed", 0)
                         for t, p in zip(minutes, px)])
    resample(con, "XAUUSDT", from_ms(int(minutes[0])), from_ms(FRIDAY_CLOSE), DERIVED_TIMEFRAMES, calendar=cal)
    con.close()
    return app, load_features_config(d), d


def _dl(app):
    return Downloader(RetryPolicy.from_config(app.download), opener=FakeBinanceRestOpener([], []), sleep=lambda s: None)


def test_gold_tick_on_a_weekend_is_quiet_and_complete_through_the_clock(gold_env):
    app, fcfg, config_dir = gold_env
    a = Fake("s_fake", [ms(2024, 7, 11, 10), ms(2024, 7, 12, 20, 45)])
    now = from_ms(ms(2024, 7, 13, 12, 0, 30))  # Saturday
    live = LiveConfig(cost_profile="costs_cfd_justmarkets_xauusd.yaml")
    out = run_live_tick(app, fcfg, live, config_dir, now=now, downloader=_dl(app), strategies=[a])
    assert out.status == "ok" and out.detail == "market closed"
    assert out.through_ms == ms(2024, 7, 13, 12, 0)  # nothing more can happen while closed: the loop need not retry
    root = app.data.data_dir / "markets" / "XAUUSDT" / "signals"
    assert [s.event_time_ms for s in read_signals(root, "s_fake")] == a.times
    assert not (app.data.data_dir / "signals").exists()  # the BTC record is untouched
    summary = json.loads((app.data.data_dir / "markets" / "XAUUSDT" / "paper" / "strategies_summary.json").read_text(encoding="utf-8"))
    assert summary["strategies"]["s_fake"]["signals"] == 2


def test_gold_data_that_stopped_on_friday_is_stale_on_monday(gold_env):
    app, fcfg, config_dir = gold_env
    a = Fake("s_fake", [])
    out = run_live_tick(app, fcfg, LiveConfig(cost_profile="costs_cfd_justmarkets_xauusd.yaml"), config_dir,
                        now=from_ms(ms(2024, 7, 15, 12)), downloader=_dl(app), strategies=[a])
    assert out.status == "stale" and a.scans == []
    # 14 h of trading time have passed since the last bar (Sunday 22:00 -> Monday 12:00), not 63 h of wall time
    assert out.detail == f"newest 1m bar is {14 * 3600:.0f}s old"


def test_live_config_markets_validate_and_share_settings():
    live = load_live_config()
    gold = next(m for m in live.markets if m.instrument == "XAUUSDT")
    view = live.for_market(gold)
    assert view.strategies == gold.strategies and view.cost_profile == gold.cost_profile and view.markets == ()
    assert view.poll_seconds == live.poll_seconds and view.telegram == live.telegram
    assert "crowded_shorts" not in {s.kind for s in gold.strategies}  # its funding rule cannot fire on gold
    s = LiveStrategyConfig(id="a", kind="s4_impulse_retest")
    with pytest.raises(ValueError, match="unique"):
        LiveConfig(markets=(LiveMarketConfig(instrument="X", cost_profile="c.yaml", strategies=(s,)),
                            LiveMarketConfig(instrument="X", cost_profile="c.yaml")))
    with pytest.raises(ValueError, match="unique"):
        LiveMarketConfig(instrument="X", cost_profile="c.yaml", strategies=(s, s))


def _outcome(status: str, through: int | None, detail: str = "") -> LiveTickOutcome:
    return LiveTickOutcome(status, None, through, None, detail=detail)


def test_loop_keeps_each_markets_progress_and_labels_its_alerts(tmp_path):
    alerts: list[tuple[str, str]] = []
    calls = {"btc": 0, "gold": 0}
    gold_results = [_outcome("stale", None, "newest 1m bar is 900s old"), _outcome("ok", 15 * 60_000 * 5)]

    def btc(now):
        calls["btc"] += 1
        return _outcome("ok", 15 * 60_000 * 5)

    def gold(now):
        calls["gold"] += 1
        return gold_results.pop(0)

    deps = LoopDeps(live_tick=btc, legacy_tick=None, send_telegram=None, poll_commands=None,
                    queue_system=lambda key, title, detail: alerts.append((key, title)), queue_daily_summary=None,
                    market_ticks={"XAUUSDT": gold})
    live = LiveConfig(event_delay_seconds=0)
    state = LoopState()
    now = from_ms(15 * 60_000 * 5 + 1000)
    asyncio.run(poll_once(live, deps, state, now, tmp_path / "log.jsonl"))
    ms_ = state.extra["markets"]["XAUUSDT"]
    assert state.done_through_ms == 15 * 60_000 * 5 and ms_["done_through_ms"] is None  # gold did not advance
    assert ms_["stale_alerted"] and alerts[0][1] == "XAUUSDT: market data stale"
    asyncio.run(poll_once(live, deps, state, now, tmp_path / "log.jsonl"))
    assert calls == {"btc": 1, "gold": 2}  # BTC is done through the due close; only gold is retried
    assert ms_["done_through_ms"] == 15 * 60_000 * 5 and not ms_["stale_alerted"]
    assert len(alerts) == 1
    logged = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e.get("market") == "XAUUSDT" for e in logged)


def test_telegram_shows_gold_with_its_label_and_commands_cover_every_market(tmp_path):
    from arven.engine.grading import Grade
    from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
    from arven.engine.signal_store import append_signal
    from arven.telegram.commands import CommandContext, handle_command
    from arven.telegram.messages import format_new_signal

    def sig(symbol: str, t: int) -> EngineSignal:
        return EngineSignal(symbol=symbol, side=1, strategy_id="s4_impulse_retest", strategy_version="v1", grade=Grade.EXPERIMENTAL,
                            event_time_ms=t, entry_reference=100.0, stop=99.0, tp_ladder=(TPLevel(1.0, 1.0, 101.0),), risk_fraction=0.01,
                            confidence=0.5, regime="n/a", reasons=("x",), risk_checks=(), versions=SignalVersions("v", "h", None))

    assert "GOLD XAUUSD (prices: Binance XAUUSDT) LONG" in format_new_signal(sig("XAUUSDT", 0))
    assert "BTCUSDT LONG" in format_new_signal(sig("BTCUSDT", 0))
    btc_root, gold_root = tmp_path / "signals", tmp_path / "markets" / "XAUUSDT" / "signals"
    append_signal(btc_root, sig("BTCUSDT", 1_000_000))
    append_signal(gold_root, sig("XAUUSDT", 2_000_000))
    ctx = CommandContext(SimpleNamespace(), btc_root, tmp_path / "hb.json", 3_000_000, (("Gold", gold_root),))  # type: ignore[arg-type]
    lines = handle_command("/signals", "1", ctx).splitlines()  # type: ignore[union-attr]
    assert len(lines) == 2 and "BTCUSDT" in lines[0] and "GOLD XAUUSD" in lines[1]
    strategies = handle_command("/strategies", "1", ctx)
    assert "s4_impulse_retest: 1 signals" in strategies and "Gold: s4_impulse_retest: 1 signals" in strategies  # type: ignore[operator]


def test_backup_includes_the_gold_record_and_the_session_calendar(tmp_path):
    import zipfile

    from arven.live.backup import make_backup

    data, config = tmp_path / "data", tmp_path / "config"
    (data / "markets" / "XAUUSDT" / "signals" / "s4").mkdir(parents=True)
    (data / "markets" / "XAUUSDT" / "signals" / "s4" / "signals.jsonl").write_text("{}\n", encoding="utf-8")
    (data / "markets" / "XAUUSDT" / "paper" / "run1").mkdir(parents=True)
    (data / "markets" / "XAUUSDT" / "paper" / "strategies_summary.json").write_text("{}", encoding="utf-8")
    (data / "markets" / "XAUUSDT" / "paper" / "run1" / "big.csv").write_text("x", encoding="utf-8")
    (config / "sessions").mkdir(parents=True)
    (config / "sessions" / "cme_metals_closures.csv").write_text("start_utc,end_utc,reason,source\n", encoding="utf-8")
    (config / "live.yaml").write_text("a: 1\n", encoding="utf-8")
    res = make_backup(data, config, datetime(2026, 10, 18, tzinfo=UTC))
    names = set(zipfile.ZipFile(res.path).namelist())
    assert "data/markets/XAUUSDT/signals/s4/signals.jsonl" in names
    assert "data/markets/XAUUSDT/paper/strategies_summary.json" in names
    assert "data/markets/XAUUSDT/paper/run1/big.csv" not in names  # hourly run directories are re-computable
    assert "config/sessions/cme_metals_closures.csv" in names and "config/live.yaml" in names
