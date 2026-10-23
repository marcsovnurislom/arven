"""Pre-registered check (2026-10-24, owner: "signals on all timeframes"): the live S7 configuration, unchanged except
``tf``, on 1h and 4h - BTC and gold, development and validation, once.

Rule, written before the run and committed with this file: for each market and timeframe, report trades, total and mean
net R (CFD costs, one trade at a time) on development and validation, and the random-entry control on validation (200
draws, seed 7, ``s7_study.random_control``). Verdict **supported** only if validation has >= 30 trades **and** its mean R
is above the control's 95th percentile; otherwise **not supported**. Whatever the verdict, the owner asked for the
signals: ``s7_1h`` / ``s7_4h`` run in the live loop as paper, EXPERIMENTAL, with their own forward record; nothing is
tuned on these numbers. Every run is appended to ``data/s7_study/evaluations.log``; the sealed test is never requested.

Usage: PYTHONPATH=src python scripts/research/s7_timeframes.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_study as st  # noqa: E402

from arven.core.live_config import load_live_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402


def main() -> None:
    base = dict(next(s.params for s in load_live_config().strategies if s.id == "s7_trend_break_fib"))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False).stdout.strip())
    results = {}
    for instrument in (None, "XAUUSD"):
        studies = {p: st.Study(p, instrument=instrument) for p in (BacktestPeriod.DEVELOPMENT, BacktestPeriod.VALIDATION)}
        for tf in ("1h", "4h"):
            cfg = base | {"tf": tf}
            row = {}
            for period, study in studies.items():
                m = study.evaluate(cfg, "cfd")
                row[period.value] = {k: m.get(k) for k in ("setups", "trades", "total_r", "mean_r", "win_rate")}
            val = studies[BacktestPeriod.VALIDATION]
            control = st.random_control(val, val.outcomes(cfg, "cfd"), val.costs["cfd"], 200)
            v = row["validation"]
            supported = (v["trades"] or 0) >= 30 and v["mean_r"] is not None and v["mean_r"] > control["p95"]
            row |= {"random_control_val": control, "verdict": "supported" if supported else "not supported"}
            name = f"{instrument or 'BTCUSDT'} {tf}"
            results[name] = row
            line = (f"{datetime.now(UTC).isoformat()} s7_timeframes {name} (live S7, tf={tf}) dev {row['development']['trades']}/"
                    f"{row['development']['total_r']:+.2f}R val {v['trades']}/{v['total_r']:+.2f}R mean {v['mean_r']} vs control p95 "
                    f"{control['p95']:+.3f} verdict={row['verdict']} commit={commit} dirty={dirty}\n")
            with Path("data/s7_study/evaluations.log").open("a", encoding="utf-8") as fh:
                fh.write(line)
            print(line.strip(), flush=True)
    Path("data/s7_study/timeframes.json").write_text(json.dumps(results, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
