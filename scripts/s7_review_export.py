"""Export S7 detector setups for the owner's visual check (docs/strategy_s7_trend_break_fib.md section 8).

Runs the detector on development-period BTC bars of one timeframe and writes ``data/s7_review/setups_<tf>.json`` with a
seeded sample of setups. Each setup carries only the candles **up to its arming bar** - nothing after it - so the owner
judges the pattern definition, never the outcome. Usage:
    PYTHONPATH=src python scripts/s7_review_export.py [1h|4h|15m] [sample_size]
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from dataclasses import asdict

from arven.core.config import load_config
from arven.core.splitguard import BacktestPeriod
from arven.core.time import from_ms
from arven.core.timeframes import Timeframe
from arven.data.reader import load_feature_inputs, open_readonly
from arven.engine.strategy_s7 import S7Params, S7Setup, detect_setups
from arven.runs import make_guard

TFS = {"15m": Timeframe.M15, "1h": Timeframe.H1, "4h": Timeframe.H4}
CONTEXT_BARS = 30
SEED = 7


def to_json(s: S7Setup, tf: str, t_ms, o, h, lo, c) -> dict:
    first = max(0, min(s.line.a_index, s.level0_index) - CONTEXT_BARS)
    window = range(first, s.arm_index + 1)
    tm = lambda i: int(t_ms[i])  # noqa: E731
    return {
        "id": f"{tf}-{tm(s.arm_index)}-{'L' if s.side == 1 else 'S'}",
        "timeframe": tf, "side": s.side, "arm_time_ms": tm(s.arm_index),
        "line": {"points": [{"timeMs": tm(s.line.a_index), "price": s.line.a_price}, {"timeMs": tm(s.cross_index), "price": float(s.line.at(s.cross_index))}]},
        "touches": [{"timeMs": tm(i), "price": float(h[i] if s.side == 1 else lo[i])} for i in s.touches],
        "h_last": s.h_last, "cross_time_ms": tm(s.cross_index), "break_time_ms": tm(s.break_index),
        "range": None if s.range_box is None else {"start_ms": tm(s.range_box.start), "end_ms": tm(s.range_box.end), "top": s.range_box.top, "bottom": s.range_box.bottom},
        "level0": {"timeMs": tm(s.level0_index), "price": s.level0}, "level1": {"timeMs": tm(s.level1_index), "price": s.level1},
        "fib": {str(r): s.fib(r) for r in (0.0, 0.5, 0.618, 1.0, 1.272, 1.618, 2.0)},
        "zone": {"low": s.zone_low, "high": s.zone_high},
        "confluence": [{**asdict(z), "timeMs": tm(z.index)} for z in s.confluence], "confluence_score": s.confluence_score,
        "candles": [{"t": tm(i), "o": float(o[i]), "h": float(h[i]), "l": float(lo[i]), "c": float(c[i]), "v": 0.0, "complete": True} for i in window],
    }


def main(tf: str = "1h", sample: int = 40) -> None:
    app = load_config()
    window = make_guard(app).resolve(BacktestPeriod.DEVELOPMENT)
    con = open_readonly(app.data.database_path)
    try:
        bars = load_feature_inputs(con, app, start=app.data.history_start, end=from_ms(window.end_ms)).bars[TFS[tf]]
    finally:
        con.close()
    params = S7Params()
    setups = detect_setups(bars.open, bars.high, bars.low, bars.close, params)
    picked = sorted(random.Random(SEED).sample(range(len(setups)), min(sample, len(setups))))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or None
    out_dir = app.data.data_dir / "s7_review"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "timeframe": tf, "period": "development", "params": asdict(params), "git_commit": commit, "total_setups": len(setups),
        "setups": [to_json(setups[i], tf, bars.open_time_ms, bars.open, bars.high, bars.low, bars.close) for i in picked],
        "note": "each setup shows only the candles up to its arming bar (no future data); sample seeded with 7",
    }
    path = out_dir / f"setups_{tf}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    print(f"{len(setups)} setups found on {tf}; {len(picked)} exported to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "1h", int(sys.argv[2]) if len(sys.argv) > 2 else 40)
