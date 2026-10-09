"""Deterministic fixture server for the web app's browser tests (web/e2e): the real ``arven.web`` API over a temporary data
directory seeded with *clearly synthetic* candles, three signals, a forward summary and one run manifest. Never touches the real
database. Usage: PYTHONPATH=src python scripts/web_fixture_server.py [port]"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import uvicorn

from arven.core.config import load_config
from arven.core.time import to_ms, utc_now
from arven.data.storage.db import connect
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, tp_ladder_from_r_multiples
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.engine.signal_store import append_signal, append_update
from arven.web.app import create_app

HOUR = 3_600_000
TF_MS = {"5m": 300_000, "15m": 900_000, "1h": HOUR, "4h": 4 * HOUR}


def price(i: int) -> float:
    return 80_000 + 900 * math.sin(i / 17.0) + 250 * math.sin(i / 5.0)


def seed(data_dir: Path):
    base = load_config()
    cfg = base.model_copy(update={"data": base.data.model_copy(update={"data_dir": data_dir})})
    now = to_ms(utc_now()) // 60_000 * 60_000
    sym = cfg.market.symbol
    with connect(cfg.data.database_path) as con:
        for i in range(400):
            t = now - (400 - i) * 60_000
            p = price(i)
            con.execute(
                "INSERT INTO ohlcv_1m (symbol, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume, trade_count, taker_buy_volume, "
                "taker_buy_quote_volume, source_key, ingested_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 80000, 1, 0.5, 40000, 'fixture', 0)",
                [sym, t, t + 59_999, p, p + 40, p - 40, p + 10],
            )
        for tf, ms in TF_MS.items():
            for i in range(1300):  # more than one 500-bar page so the chart's on-demand history loading is exercised
                t = now // ms * ms - (1300 - i) * ms
                p = price(i * (ms // 60_000) // 3)
                con.execute(
                    "INSERT INTO ohlcv (symbol, timeframe, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume, trade_count, "
                    "taker_buy_volume, taker_buy_quote_volume, bar_count, is_complete, built_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 10, 800000, 10, 5, 400000, 15, TRUE, 0)",
                    [sym, tf, t, t + ms - 1, p, p + 120, p - 120, p + 30],
                )
    root = data_dir / "signals"
    specs = [("s6_trend_pullback", 1, 6 * HOUR), ("s4_impulse_retest", -1, 3 * HOUR), ("s5_squeeze_breakout", 1, HOUR)]
    for sid, side, ago in specs:
        entry = 80_000.0
        stop = entry - side * 700
        ladder = tp_ladder_from_r_multiples(((1.5, 0.5), (2.5, 0.3), (4.0, 0.2)), entry=entry, stop=stop, side=side)
        sig = EngineSignal(
            symbol=sym, side=side, strategy_id=sid, strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=now - ago,
            entry_reference=entry, stop=stop, tp_ladder=ladder, risk_fraction=0.01, confidence=0.5, regime="FIXTURE",
            reasons=("synthetic fixture signal for browser tests",), risk_checks=(), versions=SignalVersions("fixture", "fixture", None),
        )
        append_signal(root, sig)
        if sid == "s6_trend_pullback":
            append_update(root, sid, SignalUpdate(sig.signal_id, now - ago + 30 * 60_000, SignalUpdateKind.TP_HIT, "level=TP1;fraction=0.5"))
            append_update(root, sid, SignalUpdate(sig.signal_id, now - ago + 90 * 60_000, SignalUpdateKind.CLOSED, "reason=STOP;fraction=0.5"))
    paper = data_dir / "paper"
    (paper / "run-fixture").mkdir(parents=True)
    (paper / "run-fixture" / "run.json").write_text(json.dumps({
        "run_id": "run-fixture", "created_at": "2026-10-01T00:00:00+00:00", "period": "forward", "provider": "fixture", "touched_test_set": False,
        "stress": False, "result_hash": "f" * 64, "git_commit": "fixture", "git_dirty": False,
        "metrics": {"total_return": -0.05, "max_drawdown": 0.08, "n_trades": 12, "win_rate": 0.33, "sharpe": -0.4},
    }))
    stat = {"signals": 12, "closed": 11, "open": 1, "signals_per_week": 1.5, "total_r": -1.2, "mean_r": -0.11, "win_rate": 0.36}
    (paper / "strategies_summary.json").write_text(json.dumps({
        "generated_at": "2026-10-01T00:00:00+00:00", "forward_start_ms": now - 30 * 86_400_000, "data_through_ms": now, "cost_profile": "fixture",
        "strategies": {"s4_impulse_retest": stat, "s5_squeeze_breakout": stat, "s6_trend_pullback": stat},
        "agreement_hypothesis": {"alone": {"n": 20, "mean_r": -0.1, "win_rate": 0.35}, "agreed_by_another_strategy": {"n": 6, "mean_r": -0.3, "win_rate": 0.33}},
        "trades": [
            {"t": now - (60 - i) * 12 * HOUR, "strategy": ("s4_impulse_retest", "s5_squeeze_breakout", "s6_trend_pullback")[i % 3], "side": 1 if i % 2 else -1,
             "r": round(2.2 * math.sin(i * 1.7) - 0.03 * i + 0.1, 2)}
            for i in range(60)
        ],
        "note": "fixture",
    }))
    # fixture heartbeat is dated in the future so it never reads as stale during a test run
    (paper / "heartbeat.json").write_text(json.dumps({"checked_at_ms": now + 7 * 86_400_000, "status": "ok"}))
    return cfg


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    tmp = Path(tempfile.mkdtemp(prefix="arven-web-fixture-"))
    cfg = seed(tmp)
    uvicorn.run(create_app(cfg), host="127.0.0.1", port=port, log_level="warning")
