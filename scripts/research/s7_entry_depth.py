"""Exploratory: when is S7's entry at fib 0.618 better than at fib 0.5 (owner's question, 2026-10-24)?

For every setup of the live S7 configuration on the **development** period (in-sample: the live configuration was
chosen there), each entry is simulated on its own (``simulate_setup``: no one-trade-at-a-time, so totals differ from
the official ones): E2 = limit at fib 0.618, E3 = limit at fib 0.5 (the live entry), E4 = half at each. Fib is counted
from level 0 (the live ``shallow_zone``), so 0.618 is the shallower level: it fills more often, with a longer stop and
a nearer TP1. Setups are grouped by features known at the arming close; nothing is optimised, nothing in the strategy
changes. Validation is not used (already spent); any rule suggested here needs a pre-registered forward check.

Usage: PYTHONPATH=src python scripts/research/s7_entry_depth.py [--instrument XAUUSD]  -> data/s7_study/entry_depth[_XAUUSD].json
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_study as st  # noqa: E402

from arven.backtest.strategy_s7_sim import simulate_setup  # noqa: E402
from arven.core.live_config import load_live_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.core.timeframes import Timeframe  # noqa: E402


def near(zone, price: float, pad: float) -> bool:
    return zone.low - pad <= price <= zone.high + pad


def features(study: st.Study, s, tf_ms: int) -> dict[str, str]:
    arm_close = int(study.bars[st.TFS["15m"]].open_time_ms[s.arm_index]) + tf_ms
    pad = 0.25 * s.atr
    conf618 = any(near(z, s.limit_618, pad) for z in s.confluence)
    conf05 = any(near(z, s.fib(0.5), pad) for z in s.confluence)
    h4 = study.bars[Timeframe.H4]
    k = int(np.searchsorted(h4.open_time_ms + Timeframe.H4.ms, arm_close, side="right"))  # 4h bars closed by the arming close
    closes = h4.close[max(0, k - 50):k]
    trend = 0 if len(closes) < 50 else (1 if closes[-1] > closes.mean() else -1)
    hour = (arm_close // 3_600_000) % 24
    leg = abs(s.level1 - s.level0) / s.atr
    pull = s.arm_index - s.level1_index
    return {
        "side": "long" if s.side == 1 else "short",
        "smc_zone": "at 0.618 only" if conf618 and not conf05 else "at 0.5 only" if conf05 and not conf618 else "at both" if conf05 else "none",
        "leg_atr": "<5" if leg < 5 else "5-8" if leg < 8 else ">=8",
        "pullback_bars": "1-3 (fast)" if pull <= 3 else "4-10" if pull <= 10 else ">10 (slow)",
        "trend_4h": "unknown" if trend == 0 else "with the trade" if trend == s.side else "against the trade",
        "session_utc": "00-07 Asia" if hour < 7 else "07-13 Europe" if hour < 13 else "13-21 US" if hour < 21 else "21-24 late",
        "range_before_break": "yes" if s.range_box is not None else "no",
        "level1_moves": "0" if s.level1_moves == 0 else "1-2" if s.level1_moves <= 2 else "3+",
    }


def summary(rows: list[dict]) -> dict:
    def tot(k: str) -> float:
        return float(sum(r[k] or 0.0 for r in rows))
    e2 = [r for r in rows if r["E2"] is not None]
    both = [r for r in e2 if r["E3"] is not None]
    only618 = [r for r in e2 if r["E3"] is None]
    return {
        "setups": len(rows), "filled_0618": len(e2), "filled_05": sum(r["E3"] is not None for r in rows),
        "turned_before_05": len(only618), "share_turned_before_05": round(len(only618) / len(e2), 3) if e2 else None,
        "R_E2_0618": round(tot("E2"), 2), "R_E3_05": round(tot("E3"), 2), "R_E4_split": round(tot("E4"), 2),
        "R_E2_when_turned_before_05": round(sum(r["E2"] for r in only618), 2),
        "R_E2_when_both_filled": round(sum(r["E2"] for r in both), 2), "R_E3_when_both_filled": round(sum(r["E3"] for r in both), 2),
    }


def main() -> None:
    instrument = sys.argv[2] if sys.argv[1:2] == ["--instrument"] else None
    cfg = dict(next(s.params for s in load_live_config().strategies if s.id == "s7_trend_break_fib"))
    study = st.Study(BacktestPeriod.DEVELOPMENT, instrument=instrument)
    tf, p, tp = st.split(cfg)
    setups = study.setups(tf, p)
    ctx = {e: study.context(tf, p, replace(tp, entry=e)) for e in ("E2", "E3", "E4")}
    rows = []
    for i, s in enumerate(setups):
        r = {e: (o.net_r if (o := simulate_setup(ctx[e], s, i)).status == "trade" else None) for e in ctx}
        rows.append(r | features(study, s, Timeframe.M15.ms))
    out = {"instrument": instrument or "BTCUSDT", "period": "development (in-sample)", "config": cfg, "all": summary(rows), "by": {}}
    for f in ("smc_zone", "leg_atr", "pullback_bars", "trend_4h", "session_utc", "side", "range_before_break", "level1_moves"):
        out["by"][f] = {v: summary([r for r in rows if r[f] == v]) for v in sorted({r[f] for r in rows})}
    # the owner's intuition as one rule, to compare (not a selection: a single pre-stated rule)
    hybrid = [r["E2"] if r["smc_zone"] == "at 0.618 only" else r["E3"] for r in rows]
    out["rule_0618_if_smc_only_there_else_05"] = round(float(sum(x or 0.0 for x in hybrid)), 2)
    name = "entry_depth" + (f"_{instrument}" if instrument else "") + ".json"
    path = Path("data/s7_study") / name
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    a = out["all"]
    print(f"{out['instrument']}: setups {a['setups']}, filled 0.618 {a['filled_0618']}, filled 0.5 {a['filled_05']}, turned before 0.5 {a['turned_before_05']} "
          f"({a['share_turned_before_05']}); total R  E2 {a['R_E2_0618']}  E3 {a['R_E3_05']}  E4 {a['R_E4_split']}; hybrid {out['rule_0618_if_smc_only_there_else_05']} -> {path}")
    for f, groups in out["by"].items():
        for v, g in groups.items():
            print(f"  {f:18s} {v:18s} n={g['setups']:3d} 0.618 filled {g['filled_0618']:3d} turned<0.5 {g['turned_before_05']:3d}  "
                  f"R E2 {g['R_E2_0618']:+7.2f}  E3 {g['R_E3_05']:+7.2f}  E4 {g['R_E4_split']:+7.2f}")


if __name__ == "__main__":
    main()
