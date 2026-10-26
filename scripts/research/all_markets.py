"""Every live strategy on every market, on development, validation and forward (2026-10-27, owner: "a full analysis of
all strategies on all markets and timeframes"). Research only; the sealed test (2025-01 -> 2026-07) is never requested.

Same machinery and the same unchanged parameters as the gold study (``gold_study.py``: S4-S6 signals through the event
backtester, then one trade at a time with costs; S7 through its own simulator). Nothing is tuned on these numbers.
For each strategy: trades, total / mean net R, win rate, profit factor, max drawdown (R), the same with the costs x4
(``x4``), and a **random-entry control** (same number of trades, same stop distance and holding time, random side and
start, same costs; 200 draws, seed 7): the strategy beats chance only if its mean R is above the control's 95th
percentile. Buy-and-hold over the period is reported beside it.

Pre-registered reading rule (written before any run): a strategy is **supported** on a market only if on validation it
has >= 30 trades, mean R > 0 after costs, mean R above the control's 95th percentile, and also mean R > 0 on
development. Everything else is **not supported**. With 11 markets x 9 strategies about 5 "supported" rows are
expected by chance alone at the 95 % level, so a single supported row is a lead, not a result.

Usage: PYTHONPATH=src python scripts/research/all_markets.py <INSTRUMENT> [periods...]
       (BTCUSDT uses the default configuration; history instruments: XAUUSD, XAGUSD, EURUSD, GBPUSD, crypto symbols)
Output: data/markets/<INSTRUMENT>/research/all_markets_<period>.json (BTC: data/research/all_markets_<period>.json)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

INSTRUMENT = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
os.environ["ARVEN_INSTRUMENT"] = INSTRUMENT
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gold_study as gs  # noqa: E402  (reads ARVEN_INSTRUMENT at import)

import arven.backtest.strategy_s7_sim as sim  # noqa: E402
import s7_study as st  # noqa: E402
from arven.backtest.costs import slippage_fraction, taker_fee_rate  # noqa: E402
from arven.core.config import load_config  # noqa: E402
from arven.core.live_config import load_live_config  # noqa: E402
from arven.engine.strategy_s7 import detect_setups  # noqa: E402
from arven.live.strategies import smc_types  # noqa: E402

if INSTRUMENT == "BTCUSDT":  # the default configuration (its market_root is data/)
    gs.APP = load_config(gs.CONFIG_DIR)
    gs.OUT = gs.APP.data.data_dir / "research"

S7_VARIANTS = {s.id: dict(s.params) for s in load_live_config(gs.CONFIG_DIR).markets[0].strategies if s.kind == "s7"}
DRAWS, SEED = 200, 7


def s7_trades(c: gs.Ctx, cfg: dict[str, Any], stress: bool) -> list[dict]:
    tf, p, tp = st.split(cfg)
    need = int(cfg.get("min_smc_types", 0))
    b = c.bars[st.TFS[tf]]
    close_ms = b.open_time_ms + st.TFS[tf].ms
    setups = [s for s in detect_setups(b.open, b.high, b.low, b.close, p, volume=b.volume)
              if c.window.start_ms <= int(close_ms[s.arm_index]) <= c.through and smc_types(s) >= need]
    higher = st.HIGHER[tf]
    ctx = sim.make_context(sim.S7Bars.from_series(b), sim.S7Bars.from_series(c.bars[st.LOWER[tf]]), c.m, c.costs, p, tp,
                           higher=None if higher is None else sim.S7Bars.from_series(c.bars[higher]), stress=stress,
                           calendar=gs.APP.session_calendar())
    out = []
    for r in sim.run_setups(ctx, setups):
        if r.status == "trade":
            leg = r.legs[0]
            out.append(gs.trade(r.entry_time_ms, r.exit_time_ms, r.net_r, leg.entry_price, leg.stop, 1 if leg.entry_price > leg.stop else -1))
    return sorted(out, key=lambda x: x["entry_ms"])


def stats(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "total_r": 0.0, "mean_r": None, "win_rate": None, "profit_factor": None, "max_dd_r": None}
    a = np.asarray(rs, dtype=float)
    cum = np.cumsum(a)
    gains, losses = a[a > 0].sum(), -a[a < 0].sum()
    return {"trades": int(len(a)), "total_r": float(a.sum()), "mean_r": float(a.mean()), "win_rate": float((a > 0).mean()),
            "profit_factor": float(gains / losses) if losses > 0 else None,
            "max_dd_r": float(np.max(np.maximum.accumulate(np.concatenate([[0.0], cum])) - np.concatenate([[0.0], cum])))}


def random_control(c: gs.Ctx, trades: list[dict]) -> dict[str, Any] | None:
    """Mean net R of random trades with the real trades' stop distance and holding time (random side and start minute,
    a stop hit ends the trade at -1 R, otherwise the close after the holding time; entry and exit pay the profile's
    fee + fixed slippage). The 95th percentile of the draws is the bar a strategy has to clear."""
    if len(trades) < 5:
        return None
    m = c.m
    t, hi, lo, op, cl = m.time_ms, m.high, m.low, m.open, m.close
    n = len(t)
    fee = taker_fee_rate(c.costs)
    rng = np.random.default_rng(SEED)
    means = []
    holds = [max(1, int((x["exit_ms"] - x["entry_ms"]) // 60_000)) for x in trades]
    stops = [x["stop_pct"] for x in trades]
    for _ in range(DRAWS):
        rs = []
        for hold, sp in zip(holds, stops, strict=True):
            i = int(rng.integers(0, max(1, n - hold - 1)))
            j = int(np.searchsorted(t, t[i] + hold * 60_000))
            j = min(max(j, i + 1), n - 1)
            side = 1 if rng.random() < 0.5 else -1
            o = float(op[i])
            slip = slippage_fraction(o, float(hi[i]), float(lo[i]), c.costs, False)
            entry = o * (1 + side * slip)
            stop = entry * (1 - side * sp)
            path_bad = lo[i:j].min() if side == 1 else hi[i:j].max()
            if (side == 1 and path_bad <= stop) or (side == -1 and path_bad >= stop):
                exit_px = stop * (1 - side * slip)
            else:
                exit_px = float(cl[j - 1]) * (1 - side * slip)
            risk = abs(entry - stop)
            rs.append((exit_px - entry) * side / risk - (entry + exit_px) * fee / risk)
        means.append(float(np.mean(rs)))
    q = np.quantile(means, [0.05, 0.5, 0.95])
    return {"draws": DRAWS, "seed": SEED, "p05": float(q[0]), "median": float(q[1]), "p95": float(q[2])}


def run(period: str) -> None:
    c = gs.Ctx(period)
    if INSTRUMENT == "BTCUSDT":  # BTC's live signals are tracked with the CFD profile (config/live.yaml cost_profile)
        c.costs = st.CostsConfig.model_validate(st.yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))
    try:
        recorded = gs.load(f"signals_{period}.json")["signals"]
    except FileNotFoundError:
        gs.record(period)
        recorded = gs.load(f"signals_{period}.json")["signals"]
    res: dict[str, Any] = {"instrument": INSTRUMENT, "period": period, "window_ms": [c.window.start_ms, c.window.end_ms],
                           "buy_and_hold_pct": float(c.m.close[-1] / c.m.open[0] - 1) * 100, "costs": c.costs.model_dump(),
                           "strategies": {}}
    for sid, sigs in recorded.items():
        t0 = time.perf_counter()
        base, _ = gs.recorded_replay(c, sigs, False)
        x4, _ = gs.recorded_replay(c, sigs, True)
        res["strategies"][sid] = {"cost": stats([x["r"] for x in base]), "x4": stats([x["r"] for x in x4]),
                                  "control": random_control(c, base), "trades": base}
        print(f"  {sid}: {len(base)} trades ({time.perf_counter() - t0:.0f}s)", flush=True)
    for sid, cfg in S7_VARIANTS.items():
        t0 = time.perf_counter()
        base, x4 = s7_trades(c, cfg, False), s7_trades(c, cfg, True)
        res["strategies"][sid] = {"cost": stats([x["r"] for x in base]), "x4": stats([x["r"] for x in x4]),
                                  "control": random_control(c, base), "trades": base}
        print(f"  {sid}: {len(base)} trades ({time.perf_counter() - t0:.0f}s)", flush=True)
    gs.save(f"all_markets_{period}.json", res)


if __name__ == "__main__":
    for p in sys.argv[2:] or ["development", "validation", "forward"]:
        print(f"== {INSTRUMENT} {p}", flush=True)
        run(p)
