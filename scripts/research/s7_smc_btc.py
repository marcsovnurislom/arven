"""S7 on BTC: one pre-registered hypothesis carried over from the gold S7 grid (docs/RESULTS_GOLD.md section 5a).
Research-only; nothing in ``src/`` imports this. The sealed test period is never requested.

Pre-registered 2026-10-21, committed before the first run:
- Hypothesis H: S7 as live (``config/live.yaml``) but **without the FVG impulse rule** and **only setups with at least two
  different SMC zone types (FVG, iFVG, order block) overlapping the entry zone** at the arming close - stop fib 0.1 (the
  live S1), everything else unchanged. On gold this was -0.1 R (43 trades) on development and +4.5 R (23) on validation;
  it was noticed after validation had been seen, so gold is not evidence for it - BTC is the independent check.
- Verdict, BTC, CFD costs: H is **supported** only if its mean R is > 0 on development AND on validation AND its
  validation mean R is above the 95th percentile of the random-entry control. Otherwise **not supported**. Forward and
  x4 costs are reported, not part of the verdict.
- Reported for context (no verdict): the live configuration; "no FVG impulse, no zone filter" (to separate the two
  changes); H with the other stops (fib 0, 0.2, 0.3, below fib 0 by 0.25 ATR, close beyond fib 0).
Output ``data/s7_study/smc_btc.json``; every run is appended to ``data/s7_study/evaluations.log``.
Usage:  PYTHONPATH=src python scripts/research/s7_smc_btc.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_study as st  # noqa: E402

import arven.backtest.strategy_s7_sim as sim  # noqa: E402
from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account  # noqa: E402
from arven.core.live_config import load_live_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.engine.strategy_s7_plan import S7TradeParams  # noqa: E402

LIVE = next(s.params for s in load_live_config().strategies if s.kind == "s7")
SMC = ("fvg", "ifvg", "order_block")
PERIODS = {"development": BacktestPeriod.DEVELOPMENT, "validation": BacktestPeriod.VALIDATION, "forward": BacktestPeriod.FORWARD}
STOPS = ("F01", "F0", "F02", "F03", "S2", "C0")
_ORIG_STOP = sim.stop_price
_STOP = {"key": "F01"}


def two_plus_smc(s) -> bool:
    return len({z.kind for z in s.confluence if z.kind in SMC}) >= 2


def _stop(s, tp):
    k = _STOP["key"]
    if k in ("F01", "C0"):  # the plan's own S1 (fib 0.1) and S3 (close beyond level 0 + hard stop 1 ATR beyond it)
        return _ORIG_STOP(s, tp)
    if k == "S2":
        return s.level0 - s.side * 0.25 * s.atr
    return s.fib({"F0": 0.0, "F02": 0.2, "F03": 0.3}[k])


def run(study: st.Study, impulse: str, keep, stop: str, stress: bool) -> list:
    tf, p, _ = st.split(dict(LIVE, impulse=impulse))
    setups = [s for s in study.setups(tf, p) if keep(s)]
    _STOP["key"] = stop
    tp = S7TradeParams(entry="E3", stop="S3" if stop == "C0" else "S1", management="V0")
    return sim.run_setups(study.context(tf, p, tp, "cfd", stress), setups), len(setups)


def summary(outs: list, n_setups: int) -> dict[str, Any]:
    trades = sorted((o for o in outs if o.status == "trade"), key=lambda o: o.entry_time_ms)
    rs = np.array([o.net_r for o in trades])
    acc = summarize_account(replay_account([TradeForAccount(sum(lg.weight * abs(lg.entry_price - lg.stop) for lg in o.legs), o.net_r)
                                            for o in trades]), AccountRules())
    ci = None
    if len(rs):
        rng = np.random.default_rng(st.SEED)
        ci = np.percentile([rng.choice(rs, len(rs)).mean() for _ in range(4000)], [2.5, 97.5]).tolist()
    return {"setups": n_setups, "trades": int(len(rs)), "total_r": float(rs.sum()) if len(rs) else 0.0,
            "mean_r": float(rs.mean()) if len(rs) else None, "win": float((rs > 0).mean()) if len(rs) else None,
            "mean_r_ci95": ci, "account_1pct": acc}


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False).stdout.strip())
    out: dict[str, Any] = {"hypothesis": __doc__, "git_commit": commit, "git_dirty": dirty, "live_config": LIVE, "periods": {}}
    sim.stop_price = _stop
    try:
        for period, pk in PERIODS.items():
            study = st.Study(pk)
            row: dict[str, Any] = {}
            outs, n = run(study, "none", two_plus_smc, "F01", False)
            row["H"] = summary(outs, n)
            row["H"]["random_control_cfd"] = st.random_control(study, outs, study.costs["cfd"], 200)
            row["H_x4"] = summary(*run(study, "none", two_plus_smc, "F01", True))
            row["live"] = summary(*run(study, LIVE["impulse"], lambda s: True, "F01", False))
            row["no_impulse_no_filter"] = summary(*run(study, "none", lambda s: True, "F01", False))
            row["H_stops"] = {stop: summary(*run(study, "none", two_plus_smc, stop, False)) for stop in STOPS}
            out["periods"][period] = row
            h, rc = row["H"], row["H"]["random_control_cfd"]
            print(f"{period:11s} H: {h['trades']} trades, {h['total_r']:+.2f} R, mean {h['mean_r']}, CI {h['mean_r_ci95']}, "
                  f"random p95 {rc['p95']:+.3f}; x4 {row['H_x4']['total_r']:+.2f} R; live {row['live']['trades']} / "
                  f"{row['live']['total_r']:+.2f} R; no impulse, no filter {row['no_impulse_no_filter']['total_r']:+.2f} R", flush=True)
    finally:
        sim.stop_price = _ORIG_STOP
    dev, val = out["periods"]["development"]["H"], out["periods"]["validation"]["H"]
    supported = bool(dev["mean_r"] and dev["mean_r"] > 0 and val["mean_r"] and val["mean_r"] > 0
                     and val["mean_r"] > val["random_control_cfd"]["p95"])
    out["verdict"] = "supported" if supported else "not supported"
    path = Path("data/s7_study/smc_btc.json")
    path.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    with Path("data/s7_study/evaluations.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(UTC).isoformat()} smc_btc H (no FVG impulse, 2+ SMC zone types, stop fib 0.1) "
                f"dev {dev['trades']}/{dev['total_r']:+.2f}R val {val['trades']}/{val['total_r']:+.2f}R verdict={out['verdict']} "
                f"commit={commit} dirty={dirty}\n")
    print("verdict:", out["verdict"], "->", path)


if __name__ == "__main__":
    main()
