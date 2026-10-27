"""S7 v2 - pre-registered check (2026-10-28, owner: "yes, start S7 v2"). Rule written and committed BEFORE any v2 run.

Where v2 comes from: the owner's 44 verdicts on S7 trades (docs/ANALIZ_VSEH_STRATEGIY.md section 11) and a check of
his reasons on DEVELOPMENT only (2020-01 -> 2023-07, 9 markets). Validation and the new data were not used.

S7 v2 = the live S7 15m configuration (s7_trend_break_fib in config/live.yaml) with exactly three changes, nothing
else and no further tuning:
  1. line_from_major_high: true  - the line starts at the highest high (lowest low) of the search window
                                   ("the line must start from the earlier minimum");
  2. max_wick_pierce_atr: 0.5    - no candle between the first anchor and the break crosses the line by more than
                                   0.5 ATR (was 0.8; "crooked line, a low in the middle sticks out");
  3. cluster_min_bars: 10        - counted touches at least 10 bars apart (was 5; "touches too close, in a range,
                                   really only 2 touches").

Evaluation: the same detector, one-trade-at-a-time simulator, costs (each market's live profile) and $1000 account as
the S7 trades page (scripts/s7_all_trades_export.py), on development (information only), validation (9 markets with
history) and the new data (2026-07-01 -> today, 12 markets). The sealed test is never requested.

VERDICT RULE (fixed now):
  SUPPORTED only if ALL of
    (a) validation, all 9 markets pooled: >= 100 trades, mean net R > 0 and the 95 % interval of the mean
        (normal approximation, arven.live.review.forward_review) wholly above 0;
    (b) the new data, all 12 markets pooled: mean net R > 0.
  Otherwise NOT SUPPORTED. Either way the result is written down; v2 is not re-tuned on these numbers. If supported,
  v2 goes into the live loop as a separate paper strategy (id s7_v2, EXPERIMENTAL) with its own forward record.

Every run appends a line to data/s7_study/evaluations.log. Trades are written as model "s7_v2" so the S7 trades page
shows every v2 trade next to v1.

Usage: ARVEN_DB_WAIT_SECONDS=300 PYTHONPATH=src python scripts/research/s7_v2.py <INSTRUMENT> [periods...]
       PYTHONPATH=src python scripts/research/s7_v2.py --verdict
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_all_trades_export as ex  # noqa: E402

from arven.core.live_config import load_live_config  # noqa: E402
from arven.live.review import forward_review  # noqa: E402

V2_CHANGES = {"line_from_major_high": True, "max_wick_pierce_atr": 0.5, "cluster_min_bars": 10}
HISTORY = ["BTCUSDT", "XAUUSD", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]
FORWARD = HISTORY[:1] + ["XAUUSDT"] + HISTORY[2:] + ["XAGUSDT", "EURUSD", "GBPUSD"]


def v2_config() -> dict:
    base = dict(next(s.params for s in load_live_config().strategies if s.id == "s7_trend_break_fib"))
    return base | V2_CHANGES


def out_dir(instrument: str) -> Path:
    folder = ex.OUT_AS.get(instrument, instrument)
    return Path("data/s7_study") if instrument == "BTCUSDT" else Path("data/markets") / folder / "s7_study"


def run(instrument: str, periods: list[str]) -> None:
    d_out = out_dir(instrument)
    d_out.mkdir(parents=True, exist_ok=True)
    index_path = d_out / "trades_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for period in periods:
        d = ex.Data(instrument, period)
        if len(d.m) == 0:
            print(f"{instrument} {period}: no data", flush=True)
            continue
        s = ex.export(d, instrument, "s7_v2", v2_config(), period, d_out)
        index[f"s7_v2|{period}"] = {"model": "s7_v2", "period": period, **{k: s[k] for k in ("trades", "setups", "win_rate", "total_r", "mean_r", "profit_factor")},
                                    "account_return": s["account"]["return"], "max_drawdown": s["account"]["max_drawdown"]}
        print(f"{instrument} {period} s7_v2: {s['trades']} trades, {s['total_r']:+.1f} R", flush=True)
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")


def pooled(period: str, markets: list[str], model: str) -> list[float]:
    rs: list[float] = []
    for inst in markets:
        f = out_dir(inst) / f"trades_{model}_{period}.json"
        if f.exists():
            rs += [t["net_r"] for t in json.loads(f.read_text(encoding="utf-8"))["trades"]]
    return rs


def verdict() -> None:
    out = {}
    for model in ("s7_trend_break_fib", "s7_v2"):
        out[model] = {p: forward_review(pooled(p, FORWARD if p == "forward" else HISTORY, model)) | {"total_r": sum(pooled(p, FORWARD if p == "forward" else HISTORY, model))}
                      for p in ("development", "validation", "forward")}
    v, f = out["s7_v2"]["validation"], out["s7_v2"]["forward"]
    ok = v["n"] >= 100 and (v["mean_r"] or 0) > 0 and v["ci_low"] is not None and v["ci_low"] > 0 and (f["mean_r"] or 0) > 0
    out["verdict"] = "SUPPORTED" if ok else "NOT SUPPORTED"
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    line = (f"{datetime.now(UTC).isoformat()} s7_v2 val n={v['n']} mean={v['mean_r']} ci=[{v['ci_low']}, {v['ci_high']}] "
            f"forward n={f['n']} mean={f['mean_r']} verdict={out['verdict']} commit={commit}\n")
    with Path("data/s7_study/evaluations.log").open("a", encoding="utf-8") as fh:
        fh.write(line)
    Path("data/s7_study/s7_v2_verdict.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    if sys.argv[1:] == ["--verdict"]:
        verdict()
    else:
        run(sys.argv[1], sys.argv[2:] or ["development", "validation", "forward"])
