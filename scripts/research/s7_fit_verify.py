"""Stage 3 of the S7 fit: the chosen rule of a market re-run through the project's own tracker
(arven.backtest.paper_tracker.track_signal: 1m bars, the stop wins a same-bar tie, exit fee + slippage, funding while
held) plus the entry fee, one trade at a time - the independent check of the fast scorer in s7_fit_search.py.

Usage: ARVEN_DB_WAIT_SECONDS=300 PYTHONPATH=src python scripts/research/s7_fit_verify.py <INSTRUMENT> <period> <variant> <entry>
       <filter> <stop> <tp_r> <hold_min>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s7_all_trades_export as ex  # noqa: E402
import s7_fit as fit  # noqa: E402
import s7_fit_search as fs  # noqa: E402

import arven.backtest.strategy_s7_sim as sim  # noqa: E402
from arven.backtest.costs import taker_fee_rate  # noqa: E402
from arven.backtest.paper_tracker import track_signal  # noqa: E402
from arven.engine.grading import Grade  # noqa: E402
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel  # noqa: E402
from arven.engine.strategy_s7 import detect_setups  # noqa: E402
from arven.engine.strategy_s7_plan import S7TradeParams  # noqa: E402
from arven.features.indicators import atr as atr_fn  # noqa: E402
from arven.live.strategies import S7_HIGHER, S7_LOWER, S7_TFS, s7_params  # noqa: E402
from arven.core.timeframes import Timeframe  # noqa: E402


def trades(instrument: str, period: str, variant: str, entry: str, filt: str, stop: str, tp_r: float, hold_min: int) -> list[dict]:
    d = ex.Data(instrument, period)
    tf, vname = variant.split("|")
    tfo = S7_TFS[tf]
    b = d.bars[tfo]
    atr_tf = atr_fn(b.high, b.low, b.close, 14)
    d1, h4 = fit.trend_table(d.bars[Timeframe.D1], Timeframe.D1), fit.trend_table(d.bars[Timeframe.H4], Timeframe.H4)
    cfg = fit.base_cfg() | fit.DETECTORS[vname] | {"tf": tf}
    _, p, _ = s7_params(cfg)
    close_ms = b.open_time_ms + tfo.ms
    through = (int(d.m.time_ms[-1]) + 60_000) // 900_000 * 900_000
    setups = [s for s in detect_setups(b.open, b.high, b.low, b.close, p, volume=b.volume) if d.window.start_ms <= int(close_ms[s.arm_index]) <= through]
    feats = [fit.setup_features(s, b, tfo.ms, s.arm_index, d1, h4, atr_tf) for s in setups]
    fd = {f"f_{k}": np.array([f[k] for f in feats]) for k in (feats[0] if feats else {})} | {"side": np.array([s.side for s in setups])}
    if setups:  # the leg-size median of the fit (as in the search's filter) is taken on these setups' own rows
        mask = fs.FILTERS[filt](fd)
    else:
        mask = np.array([], dtype=bool)
    higher = S7_HIGHER[tf]
    ctx = sim.make_context(sim.S7Bars.from_series(b), sim.S7Bars.from_series(d.bars[S7_LOWER[tf]]), d.m, d.costs, p,
                           S7TradeParams(entry=entry, stop="S3", management="V0"),
                           higher=None if higher is None else sim.S7Bars.from_series(d.bars[higher]), calendar=d.app.session_calendar())
    fee = taker_fee_rate(d.costs)
    out, free = [], -1
    cands = []
    for k, s in enumerate(setups):
        if not mask[k]:
            continue
        o = sim.simulate_setup(ctx, s, k)
        if o.fills:
            cands.append((o.fills[0], s))
    for f, s in sorted(cands, key=lambda x: x[0].time_ms):
        if f.time_ms < free:
            continue
        stp = s.fib(0.1) if stop == "S1" else s.level0 - s.side * (0.25 if stop == "S2" else 1.0) * s.atr
        risk = (f.price - stp) * s.side
        if risk <= 0:
            continue
        tpx = f.price + s.side * tp_r * risk
        sig = EngineSignal(symbol=d.app.market.symbol, side=s.side, strategy_id="s7_fit", strategy_version="v1", grade=Grade.EXPERIMENTAL,
                           event_time_ms=f.time_ms, entry_reference=f.price, stop=stp, tp_ladder=(TPLevel(tp_r, 1.0, tpx),), risk_fraction=0.01,
                           confidence=0.5, regime="n/a", reasons=("fit",), risk_checks=(), versions=SignalVersions("v1", "fit", None),
                           max_holding_minutes=hold_min)
        res = track_signal(sig, f.time_ms, f.price, d.m, d.costs)
        if res.resolution is None or not res.resolution.fully_closed:
            continue
        r = res.resolution.r_multiple - f.price * fee / risk
        ex_ms = max(u.time_ms for u in res.updates)
        out.append({"fill_ms": f.time_ms, "exit_ms": ex_ms, "side": s.side, "r": r})
        free = ex_ms
    return out


if __name__ == "__main__":
    inst, period, variant, entry, filt, stop, tp_r, hold = sys.argv[1:9]
    tr = trades(inst, period, variant, entry, filt, stop, float(tp_r), int(hold))
    rs = np.array([t["r"] for t in tr])
    print(json.dumps({"instrument": inst, "period": period, "trades": len(rs), "win": float(np.mean(rs > 0)) if len(rs) else 0,
                      "total_r": float(rs.sum()), "mean_r": float(rs.mean()) if len(rs) else 0}))
