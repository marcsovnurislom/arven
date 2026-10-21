"""S7 position-sizing study: the same S7 trades (development-selected configuration, CFD costs, one trade at a time) replayed
on a $1000 account under different risk rules. Research-only; nothing in ``src/`` imports this.

Input: ``data/strategy_trades/s7/<period>.json`` (``scripts/strategy_trades_export.py``) - each trade's net R and its
stop distance in $ per BTC. Sizing follows ``arven.backtest.account_sim``: size floored to the 0.01 BTC lot step, the
minimum lot used only while its stop loss is <= 5 % of equity. Rules are chosen on development only; validation and
forward are reported as they come. A seeded bootstrap (no lot rounding) gives the spread of 100-trade outcomes.
Writes ``data/s7_study/risk_study.json``. Usage:  PYTHONPATH=src python scripts/research/s7_risk_study.py
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np

PERIODS = ("development", "validation", "forward")
START, LOT, MIN_LOT, MAX_LOSS = 1000.0, 0.01, 0.01, 0.05
SEED, PATHS, PATH_TRADES = 7, 10_000, 100

Rule = Callable[[float, float], float]  # (equity, peak equity) -> risk fraction


def fixed(f: float) -> Rule:
    return lambda eq, peak: f


def dd_brake(base: float) -> Rule:
    """Full risk normally, half below a 10 % drawdown, a quarter below 20 %."""
    def rule(eq: float, peak: float) -> float:
        dd = 1 - eq / peak
        return base if dd < 0.10 else base / 2 if dd < 0.20 else base / 4
    return rule


def load(period: str) -> list[dict]:
    d = json.loads(Path(f"data/strategy_trades/s7/{period}.json").read_text(encoding="utf-8"))
    return sorted(d["trades"], key=lambda t: t["entry_time_ms"])


def replay(trades: list[dict], rule: Rule, start: float = START) -> dict:
    eq = peak = start
    max_dd, actual, skipped, wins, losses, curve = 0.0, [], 0, 0, 0, [start]
    worst = 0.0
    for t in trades:
        rpu = t["risk_per_unit"]
        f = rule(eq, peak)
        if f <= 0 or not (rpu > 0) or eq <= 0:
            skipped += 1
            curve.append(eq)
            continue
        size = math.floor(round(eq * f / rpu / LOT, 9)) * LOT
        if size < MIN_LOT:
            if MIN_LOT * rpu > eq * MAX_LOSS:
                skipped += 1
                curve.append(eq)
                continue
            size = MIN_LOT
        pnl = size * rpu * t["net_r"]
        actual.append(size * rpu / eq)
        worst = min(worst, pnl / eq)
        eq += pnl
        wins += pnl > 0
        losses += pnl <= 0
        peak = max(peak, eq)
        max_dd = max(max_dd, 1 - eq / peak)
        curve.append(eq)
    # longest losing streak in trades
    streak = best_streak = 0
    for t in trades:
        streak = streak + 1 if t["net_r"] <= 0 else 0
        best_streak = max(best_streak, streak)
    return {"final": eq, "return": eq / start - 1, "max_dd": max_dd, "trades": wins + losses, "skipped": skipped,
            "wins": wins, "losses": losses, "avg_actual_risk": float(np.mean(actual)) if actual else 0.0,
            "max_actual_risk": float(np.max(actual)) if actual else 0.0, "worst_trade": worst,
            "loss_streak": best_streak, "curve": curve}


def bootstrap(rs: np.ndarray, f: float) -> dict:
    """Pure fractional sizing (no lots): 100-trade paths resampled from ``rs``."""
    rng = np.random.default_rng(SEED)
    draws = rng.choice(rs, size=(PATHS, PATH_TRADES))
    growth = np.cumprod(1 + f * draws, axis=1)
    final = growth[:, -1] * START
    peak = np.maximum.accumulate(np.concatenate([np.ones((PATHS, 1)), growth], axis=1), axis=1)[:, 1:]
    dd = (1 - growth / peak).max(axis=1)
    return {"median_final": float(np.median(final)), "p05_final": float(np.percentile(final, 5)),
            "p95_final": float(np.percentile(final, 95)), "p_loss": float((final < START).mean()),
            "median_dd": float(np.median(dd)), "p_dd_20": float((dd >= 0.20).mean()), "p_dd_30": float((dd >= 0.30).mean()),
            "p_dd_50": float((dd >= 0.50).mean())}


def main() -> None:
    trades = {p: load(p) for p in PERIODS}
    dev_r = np.array([t["net_r"] for t in trades["development"]])
    oos_r = np.array([t["net_r"] for p in ("validation", "forward") for t in trades[p]])
    kelly = float(dev_r.mean() / np.mean(dev_r ** 2))  # growth-optimal fraction for small f, development only
    rules: dict[str, Rule] = {f"fixed {f:.2%}": fixed(f) for f in (0.0025, 0.005, 0.01, 0.02, 0.03, 0.05)}
    rules["dd brake 1%"] = dd_brake(0.01)
    rules["dd brake 2%"] = dd_brake(0.02)
    rules[f"half Kelly (dev) {kelly / 2:.2%}"] = fixed(kelly / 2)
    out: dict = {"kelly_dev": kelly, "dev_mean_r": float(dev_r.mean()), "oos_mean_r": float(oos_r.mean()),
                 "counts": {p: len(v) for p, v in trades.items()}, "rules": {}}
    whole = trades["development"] + trades["validation"] + trades["forward"]
    for name, rule in rules.items():
        res = {p: replay(trades[p], rule) for p in PERIODS}
        res["continuous"] = replay(whole, rule)
        res["oos_continuous"] = replay(trades["validation"] + trades["forward"], rule)
        out["rules"][name] = res
    out["bootstrap"] = {f"{f:.2%}": {"development": bootstrap(dev_r, f), "out_of_sample": bootstrap(oos_r, f)}
                        for f in (0.0025, 0.005, 0.01, 0.02, 0.03, 0.05)}
    Path("data/s7_study/risk_study.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    print(f"trades {out['counts']}; mean R dev {out['dev_mean_r']:+.3f}, val+fwd {out['oos_mean_r']:+.3f}; Kelly (dev) {kelly:.2%}")
    for name, res in out["rules"].items():
        line = "  ".join(f"{k[:4]} ${v['final']:.0f} ({v['return']:+.1%}) dd {v['max_dd']:.1%} risk~{v['avg_actual_risk']:.2%}/max {v['max_actual_risk']:.2%} sk{v['skipped']}"
                         for k, v in res.items())
        print(f"{name:22} {line}")
    for f, b in out["bootstrap"].items():
        print(f"boot {f}: " + "  ".join(f"{k}: med ${v['median_final']:.0f} [{v['p05_final']:.0f}..{v['p95_final']:.0f}] Ploss {v['p_loss']:.0%} "
                                         f"DD med {v['median_dd']:.0%} P>=20% {v['p_dd_20']:.0%} P>=30% {v['p_dd_30']:.0%} P>=50% {v['p_dd_50']:.0%}"
                                         for k, v in b.items()))


if __name__ == "__main__":
    main()
