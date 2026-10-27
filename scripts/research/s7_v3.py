"""S7 v3 - pre-registered check (2026-10-28, owner: "yes, start" - the next S7 idea after v2's NOT SUPPORTED: not the
line's geometry but WHEN NOT TO ENTER). Rule written and committed BEFORE any v3 run.

Why: in every period ~57 % of S7 trades hit the full stop before TP1 (docs/ANALIZ_VSEH_STRATEGIY.md section 10). The
classic remedy is to trade only with the trend of a higher timeframe.

S7 v3 = S7 v2 (scripts/research/s7_v2.py: the live S7 15m + line_from_major_high, max_wick_pierce_atr 0.5,
cluster_min_bars 10) + ONE filter, chosen now and not tuned:
  daily trend - at the setup's arming close, take the last COMPLETED 1d bar (its close time <= the arming close; no
  look-ahead) and the 50-day EMA of daily closes up to and including it. A LONG setup is kept only if that daily close
  is above its EMA50, a SHORT only if below. Days without an EMA (fewer than 50 daily closes) -> the setup is dropped.
EMA: arven.features.indicators.ema(span=50, min_count=50) over the stored complete 1d bars (UTC days).

Evaluation exactly as v2 (same markets, periods, costs, simulator, account): development (information), validation
(9 markets), the new data (2026-07-01 -> today, 12 markets); the sealed test is never requested.

VERDICT RULE (fixed now, the same bar as v2):
  SUPPORTED only if ALL of
    (a) validation, 9 markets pooled: >= 100 trades, mean net R > 0, 95 % interval of the mean wholly above 0;
    (b) the new data, 12 markets pooled: mean net R > 0.
  Otherwise NOT SUPPORTED; written down either way, no re-tuning (no other EMA length, no 4h variant) on these numbers.
  If supported: a separate paper strategy s7_v3 (EXPERIMENTAL) in the live loop.

Trades are written as model "s7_v3" for the S7 trades page; every run appends to data/s7_study/evaluations.log.

Usage: ARVEN_DB_WAIT_SECONDS=300 PYTHONPATH=src python scripts/research/s7_v3.py <INSTRUMENT> [periods...]
       PYTHONPATH=src python scripts/research/s7_v3.py --verdict
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s7_all_trades_export as ex  # noqa: E402
import s7_v2 as v2  # noqa: E402

from arven.core.timeframes import Timeframe  # noqa: E402
from arven.features.indicators import ema  # noqa: E402
from arven.live.review import forward_review  # noqa: E402

EMA_DAYS = 50
DAY_MS = Timeframe.D1.ms


def trend_filter(d: ex.Data):
    """``keep(setup, arm_close_ms)``: with the daily trend as of the arming close (see the module docstring)."""
    b = d.bars[Timeframe.D1]
    ok = b.complete & np.isfinite(b.close)
    closes_t = b.open_time_ms[ok] + DAY_MS  # the daily bar's close time = when it becomes known
    close = b.close[ok]
    e = ema(close, EMA_DAYS, min_count=EMA_DAYS)

    def keep(s, arm_close_ms: int) -> bool:
        i = int(np.searchsorted(closes_t, arm_close_ms, side="right")) - 1  # the last daily bar closed by then
        if i < 0 or not np.isfinite(e[i]):
            return False
        return bool(close[i] > e[i]) if s.side == 1 else bool(close[i] < e[i])

    return keep


def run(instrument: str, periods: list[str]) -> None:
    d_out = v2.out_dir(instrument)
    d_out.mkdir(parents=True, exist_ok=True)
    index_path = d_out / "trades_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for period in periods:
        d = ex.Data(instrument, period)
        if len(d.m) == 0:
            print(f"{instrument} {period}: no data", flush=True)
            continue
        s = ex.export(d, instrument, "s7_v3", v2.v2_config(), period, d_out, keep=trend_filter(d))
        index[f"s7_v3|{period}"] = {"model": "s7_v3", "period": period, **{k: s[k] for k in ("trades", "setups", "win_rate", "total_r", "mean_r", "profit_factor")},
                                    "account_return": s["account"]["return"], "max_drawdown": s["account"]["max_drawdown"]}
        print(f"{instrument} {period} s7_v3: {s['trades']} trades, {s['total_r']:+.1f} R", flush=True)
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")


def verdict() -> None:
    out = {}
    for model in ("s7_trend_break_fib", "s7_v2", "s7_v3"):
        out[model] = {}
        for p in ("development", "validation", "forward"):
            rs = v2.pooled(p, v2.FORWARD if p == "forward" else v2.HISTORY, model)
            out[model][p] = forward_review(rs) | {"total_r": sum(rs)}
    v, f = out["s7_v3"]["validation"], out["s7_v3"]["forward"]
    ok = v["n"] >= 100 and (v["mean_r"] or 0) > 0 and v["ci_low"] is not None and v["ci_low"] > 0 and (f["mean_r"] or 0) > 0
    out["verdict"] = "SUPPORTED" if ok else "NOT SUPPORTED"
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    with Path("data/s7_study/evaluations.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(UTC).isoformat()} s7_v3 val n={v['n']} mean={v['mean_r']} ci=[{v['ci_low']}, {v['ci_high']}] "
                 f"forward n={f['n']} mean={f['mean_r']} verdict={out['verdict']} commit={commit}\n")
    Path("data/s7_study/s7_v3_verdict.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    if sys.argv[1:] == ["--verdict"]:
        verdict()
    else:
        run(sys.argv[1], sys.argv[2:] or ["development", "validation", "forward"])
