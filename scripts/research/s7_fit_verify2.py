"""Exact check of a wide-search rule (s7_fit_search2.py): the same fills (data/s7_fit/*.npz rows) re-resolved by the
project's tracker (arven.backtest.paper_tracker.track_signal: 1m bars, stop wins a same-bar tie, exit fee + slippage
incl. the volatility part, funding while held) plus the entry fee, one trade at a time per market.

Usage: ARVEN_DB_WAIT_SECONDS=300 PYTHONPATH=src python scripts/research/s7_fit_verify2.py <variant> <entry> <filter> <stop_atr> <tp_atr> <hold_min>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s7_all_trades_export as ex  # noqa: E402
import s7_fit_search2 as s2  # noqa: E402

from arven.backtest.costs import taker_fee_rate  # noqa: E402
from arven.backtest.paper_tracker import track_signal  # noqa: E402
from arven.engine.grading import Grade  # noqa: E402
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel  # noqa: E402

PERIODS = {"development": s2.HISTORY, "validation": s2.HISTORY,
           "forward": [s2.FORWARD_OF.get(m, m) for m in s2.HISTORY] + ["XAGUSDT", "EURUSD", "GBPUSD"]}


def run(variant: str, entry: str, filt: str, k: float, tp_atr: float, hold: int) -> dict:
    out: dict = {}
    for period, markets in PERIODS.items():
        res = {}
        for inst in markets:
            d = s2.load(inst, [period])
            if d is None:
                continue
            rows = np.flatnonzero((d["variant"] == variant) & (d["entry"] == entry) & np.isfinite(d["unit_atr"]) & (d["unit_atr"] > 0)
                                  & s2.FILTERS[filt](d))
            if not len(rows):
                res[inst] = {"trades": 0, "total_r": 0.0, "wins": 0}
                continue
            data = ex.Data(inst, period)
            fee = taker_fee_rate(data.costs)
            rs, free = [], -1
            for i in rows[np.argsort(d["fill_ms"][rows], kind="stable")]:
                t, fill, side, unit = int(d["fill_ms"][i]), float(d["fill"][i]), int(d["side"][i]), float(d["unit_atr"][i])
                if t < free:
                    continue
                stop, tp = fill - side * k * unit, fill + side * tp_atr * unit
                sig = EngineSignal(symbol=data.app.market.symbol, side=side, strategy_id="s7_fit", strategy_version="v1", grade=Grade.EXPERIMENTAL,
                                   event_time_ms=t, entry_reference=fill, stop=stop, tp_ladder=(TPLevel(tp_atr / k, 1.0, tp),), risk_fraction=0.01,
                                   confidence=0.5, regime="n/a", reasons=("fit",), risk_checks=(), versions=SignalVersions("v1", "fit", None),
                                   max_holding_minutes=hold)
                r = track_signal(sig, t, fill, data.m, data.costs)
                if r.resolution is None or not r.resolution.fully_closed:
                    continue
                rs.append(r.resolution.r_multiple - fill * fee / (k * unit))
                free = max(u.time_ms for u in r.updates)
            a = np.array(rs)
            res[inst] = {"trades": int(len(a)), "total_r": float(a.sum()), "wins": int((a > 0).sum())}
            print(f"  {period} {inst}: {len(a)} trades, win {np.mean(a > 0) if len(a) else 0:.0%}, {a.sum():+.2f} R", flush=True)
        n = sum(v["trades"] for v in res.values())
        out[period] = {"markets": res, "trades": n, "win": sum(v["wins"] for v in res.values()) / n if n else 0.0,
                       "total_r": sum(v["total_r"] for v in res.values())}
        print(f"{period}: {n} trades, win {out[period]['win']:.0%}, {out[period]['total_r']:+.1f} R", flush=True)
    return out


if __name__ == "__main__":
    v, e, f, k, tp, h = sys.argv[1:7]
    o = run(v, e, f, float(k), float(tp), int(h))
    name = f"verify2_{v.replace('|', '_')}_{e}_{f.replace('&', '+').replace('<', 'lt').replace('>', 'gt')}_{k}_{tp}_{h}.json"
    (s2.OUT / name).write_text(json.dumps(o, indent=1), encoding="utf-8")
