"""S7 fit (2026-10-28, owner: "find me the ideal S7 by fitting - win rate >= 70 % with profit, tuned on each market
separately but one strategy, at least 3-4 signals a month; use every earlier analysis"). Research only.

Stage 1 - ``paths <INSTRUMENT>``: for every S7 setup of every detector variant (timeframe 15m / 30m / 1h; detector
v1 = live, v2 = line from the major extreme + straight line + touches >= 10 bars apart; impulse FVG or none) and every
entry (E1 market on reclaim, E2 limit 0.618, E3 limit 0.5), the fill from the S7 simulator and then, on 1m bars for up to
7 days, the first minute the price reached each favourable level (0.1 ... 4.0 R in 0.1 steps) and the stop, for three
stops (S1 fib 0.1, S2 level 0 - 0.25 ATR, S3 level 0 - 1 ATR) - plus causal setup features. Saved to
data/s7_fit/<INSTRUMENT>_<period>.npz. With these, any take-profit / stop / holding-time / filter combination is scored
without re-simulating:
  - stop and target touched in the same 1m bar -> the stop (worse case, CLAUDE.md rule 4); the fill bar can stop but not
    take profit;
  - costs: the market's profile, both sides (fee + fixed slippage + 0.1 x the median 1m range for the Binance profile),
    in R of that trade; funding is left out here and charged in stage 3;
  - one trade at a time per market.
Stage 2 - ``search``: per market, the best combination on 2020-01 -> 2025-01 (development + validation together, as the
owner asked: fit on all the history) under the owner's constraints; the new data (2026-07 -> now) is scored once
afterwards as the check. Stage 3 - ``verify``: the chosen rules re-run through the project's tracker with exact costs.

Usage: ARVEN_DB_WAIT_SECONDS=300 PYTHONPATH=src python scripts/research/s7_fit.py paths <INSTRUMENT> [periods...]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s7_all_trades_export as ex  # noqa: E402

import arven.backtest.strategy_s7_sim as sim  # noqa: E402
from arven.core.timeframes import Timeframe  # noqa: E402
from arven.engine.strategy_s7 import detect_setups  # noqa: E402
from arven.engine.strategy_s7_plan import S7TradeParams  # noqa: E402
from arven.features.indicators import adx as adx_fn  # noqa: E402
from arven.features.indicators import atr as atr_fn  # noqa: E402
from arven.features.indicators import rsi as rsi_fn  # noqa: E402
from arven.features.indicators import ema  # noqa: E402
from arven.live.strategies import S7_HIGHER, S7_LOWER, S7_TFS, s7_params, smc_types  # noqa: E402

OUT = Path("data/s7_fit")
LEVELS = np.round(np.arange(0.1, 4.01, 0.1), 2)
ATR_LEVELS = np.round(np.arange(0.1, 6.01, 0.1), 2)  # free stop / target distances in ATR of the setup's timeframe
HORIZON_MIN = 7 * 1440
TFS = ("15m", "30m", "1h")
DETECTORS = {
    "v1_fvg": {},
    "v1_none": {"impulse": "none"},
    "v2_fvg": {"line_from_major_high": True, "max_wick_pierce_atr": 0.5, "cluster_min_bars": 10},
    "v2_none": {"impulse": "none", "line_from_major_high": True, "max_wick_pierce_atr": 0.5, "cluster_min_bars": 10},
}
ENTRIES = ("E1", "E2", "E3")
STOPS = ("S1", "S2", "S3")
NEVER = np.iinfo(np.int64).max


def base_cfg() -> dict[str, Any]:
    return dict(ex.models()["s7_trend_break_fib"])


def first_reach(levels_px: np.ndarray, run_max: np.ndarray) -> np.ndarray:
    """Index of the first bar whose running maximum reaches each level (``NEVER`` if none)."""
    idx = np.searchsorted(run_max, levels_px, side="left")
    return np.where(idx < len(run_max), idx, NEVER)


def setup_features(s, b, tf_ms: int, arm_i: int, d1: dict[str, np.ndarray], h4: dict[str, np.ndarray], atr_tf: np.ndarray) -> dict[str, float]:
    """Everything known at the arming close (no look-ahead): trend agreement on 1d / 4h, volatility percentile, hour,
    weekday, touches, SMC types, break-leg size, line length, the 'earlier extreme' flag from the owner's verdicts."""
    t = int(b.open_time_ms[arm_i]) + tf_ms

    def trend(x: dict[str, np.ndarray]) -> float:
        i = int(np.searchsorted(x["t"], t, side="right")) - 1
        if i < 0 or not np.isfinite(x["e"][i]):
            return 0.0
        return float(np.sign(x["c"][i] - x["e"][i]) * s.side)

    lo = max(0, arm_i - 500)
    window = atr_tf[lo : arm_i + 1] / b.close[lo : arm_i + 1]
    cur = window[-1]
    pct = float(np.mean(window[np.isfinite(window)] <= cur)) if np.isfinite(cur) else np.nan
    a = s.line.a_index
    pre = slice(max(0, a - 60), a)
    earlier = (b.high[pre].max() > b.high[a]) if s.side == 1 else (b.low[pre].min() < b.low[a]) if a > 0 else False
    return {
        "trend_1d": trend(d1), "trend_4h": trend(h4), "vol_pct": pct, "hour": float((t // 3_600_000) % 24),
        "weekday": float(((t // 86_400_000) + 3) % 7), "touches": float(len(s.touches)), "smc": float(smc_types(s)),
        "leg_atr": float(abs(s.level1 - s.level0) / s.atr) if s.atr else np.nan, "line_bars": float(s.cross_index - a),
        "earlier_extreme": float(bool(earlier)),
    }


def trend_table(bars, tf: Timeframe) -> dict[str, np.ndarray]:
    ok = bars.complete & np.isfinite(bars.close)
    c = bars.close[ok]
    return {"t": bars.open_time_ms[ok] + tf.ms, "c": c, "e": ema(c, 50, min_count=50)}


def paths(instrument: str, period: str) -> Path:
    t0 = time.time()
    d = ex.Data(instrument, period)
    m = d.m
    hi, lo, cl, tm = m.high, m.low, m.close, m.time_ms
    cost_side_bps = (d.costs.fees.taker_fee_bps or 0.0) + d.costs.slippage.fixed_bps
    if d.costs.slippage.volatility_multiplier:
        cost_side_bps += d.costs.slippage.volatility_multiplier * float(np.median((hi - lo) / cl)) * 1e4
    d1, h4 = trend_table(d.bars[Timeframe.D1], Timeframe.D1), trend_table(d.bars[Timeframe.H4], Timeframe.H4)
    rows: dict[str, list] = {k: [] for k in ("variant", "entry", "side", "arm_ms", "fill_ms", "fill", "exit_lim_ms")}
    stops: dict[str, list] = {s: [] for s in STOPS}
    tp_idx: dict[str, list] = {s: [] for s in STOPS}
    sl_idx: dict[str, list] = {s: [] for s in STOPS}
    close_at: list = []  # close after 1h, 4h, 12h, 24h, 72h, 7d (time exits), as price
    fav_atr: list = []
    adv_atr: list = []
    units: list = []
    feats: dict[str, list] = {}
    hz = (60, 240, 720, 1440, 4320, HORIZON_MIN)
    for tf in TFS:
        tfo = S7_TFS[tf]
        b = d.bars[tfo]
        atr_tf = atr_fn(b.high, b.low, b.close, 14)
        rsi2, rsi14, adx14 = rsi_fn(b.close, 2), rsi_fn(b.close, 14), adx_fn(b.high, b.low, b.close, 14)
        close_ms = b.open_time_ms + tfo.ms
        through = (int(tm[-1]) + 60_000) // 900_000 * 900_000
        for vname, change in DETECTORS.items():
            cfg = base_cfg() | change | {"tf": tf}
            _, p, _ = s7_params(cfg)
            setups = [s for s in detect_setups(b.open, b.high, b.low, b.close, p, volume=b.volume)
                      if d.window.start_ms <= int(close_ms[s.arm_index]) <= through]
            if not setups:
                continue
            fts = [setup_features(s, b, tfo.ms, s.arm_index, d1, h4, atr_tf) for s in setups]
            higher = S7_HIGHER[tf]
            for entry in ENTRIES:
                tp_params = S7TradeParams(entry=entry, stop="S3", management="V0")  # S3: the widest stop, so a fill is never pre-empted
                ctx = sim.make_context(sim.S7Bars.from_series(b), sim.S7Bars.from_series(d.bars[S7_LOWER[tf]]), m, d.costs, p, tp_params,
                                       higher=None if higher is None else sim.S7Bars.from_series(d.bars[higher]), calendar=d.app.session_calendar())
                for k, s in enumerate(setups):
                    o = sim.simulate_setup(ctx, s, k)
                    if not o.fills:
                        continue
                    f = o.fills[0]
                    i0 = int(np.searchsorted(tm, f.time_ms))
                    if i0 >= len(tm) - 2:
                        continue
                    i1 = min(len(tm), i0 + HORIZON_MIN)
                    side = s.side
                    fav = (hi if side == 1 else -lo)[i0 + 1 : i1]
                    adv = (-lo if side == 1 else hi)[i0:i1]
                    run_fav, run_adv = np.maximum.accumulate(fav), np.maximum.accumulate(adv)
                    entry_px = f.price
                    rows["variant"].append(f"{tf}|{vname}"); rows["entry"].append(entry); rows["side"].append(side)
                    rows["arm_ms"].append(int(close_ms[s.arm_index])); rows["fill_ms"].append(f.time_ms); rows["fill"].append(entry_px)
                    rows["exit_lim_ms"].append(int(tm[i1 - 1]))
                    for st in STOPS:
                        stp = s.fib(0.1) if st == "S1" else s.level0 - side * (0.25 if st == "S2" else 1.0) * s.atr
                        risk = (entry_px - stp) * side
                        stops[st].append(risk)
                        if risk <= 0:
                            tp_idx[st].append(np.full(len(LEVELS), NEVER)); sl_idx[st].append(0)
                            continue
                        targets = side * entry_px + LEVELS * risk  # in "fav" units (side * price)
                        reach = first_reach(targets, run_fav)
                        tp_idx[st].append(np.where(reach == NEVER, NEVER, reach + 1))  # +1: fav starts the bar after the fill
                        sl_level = -side * stp  # adv units: -low for a long, high for a short
                        k_sl = int(np.searchsorted(run_adv, sl_level, side="left"))
                        sl_idx[st].append(k_sl if k_sl < len(run_adv) else NEVER)
                    # free stop / target in ATR of the setup's timeframe: first minute price moved k ATR for / against
                    unit = float(s.atr) if s.atr and np.isfinite(s.atr) else np.nan
                    if np.isfinite(unit) and unit > 0:
                        fr = first_reach(side * entry_px + ATR_LEVELS * unit, run_fav)
                        fav_atr.append(np.where(fr == NEVER, NEVER, fr + 1))
                        adv_atr.append(first_reach(-side * entry_px + ATR_LEVELS * unit, run_adv))
                    else:
                        fav_atr.append(np.full(len(ATR_LEVELS), NEVER)); adv_atr.append(np.full(len(ATR_LEVELS), NEVER))
                    units.append(unit)
                    close_at.append([float(cl[min(i0 + h, len(cl) - 1)]) for h in hz])
                    for kf, vf in fts[k].items():
                        feats.setdefault(kf, []).append(vf)
                    # at the fill (the last tf bar closed before it): RSI(2) / RSI(14) in the trade's direction (low =
                    # the pullback is oversold for a long / overbought for a short - the Connors idea) and ADX(14)
                    j = int(np.searchsorted(close_ms, f.time_ms, side="right")) - 1
                    for name, arr in (("rsi2_fill", rsi2), ("rsi14_fill", rsi14)):
                        v = float(arr[j]) if j >= 0 else np.nan
                        feats.setdefault(name, []).append(v if side == 1 else 100.0 - v)
                    feats.setdefault("adx_fill", []).append(float(adx14[j]) if j >= 0 else np.nan)
        print(f"  {instrument} {period} {tf}: {len(rows['side'])} fills so far ({time.time() - t0:.0f}s)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{instrument}_{period}.npz"
    np.savez_compressed(
        path, levels=LEVELS, horizons=np.array(hz), cost_side_bps=cost_side_bps, months=(d.window.end_ms - d.window.start_ms) / (30.44 * 86_400_000),
        **{k: np.array(v) for k, v in rows.items()},
        **{f"risk_{s}": np.array(stops[s]) for s in STOPS}, **{f"tp_{s}": np.array(tp_idx[s]) for s in STOPS},
        **{f"sl_{s}": np.array(sl_idx[s]) for s in STOPS}, close_at=np.array(close_at), **{f"f_{k}": np.array(v) for k, v in feats.items()},
        atr_levels=ATR_LEVELS, fav_atr=np.array(fav_atr), adv_atr=np.array(adv_atr), unit_atr=np.array(units),
    )
    print(f"{instrument} {period}: {len(rows['side'])} fills -> {path} ({time.time() - t0:.0f}s)", flush=True)
    return path


if __name__ == "__main__":
    if sys.argv[1] == "paths":
        for per in sys.argv[3:] or ["development", "validation", "forward"]:
            paths(sys.argv[2], per)
