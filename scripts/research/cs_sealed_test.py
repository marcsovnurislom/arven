"""Strategy "Crowded Shorts" - the single sealed-test evaluation (docs/strategy_crowded_shorts.md section 3).

Rules exactly as pre-registered: signal at a 1h close when fund_z <= -1.5 and oi_z >= 1.0 (missing data = no signal);
long at the next hour's open; out 24 h after the most recent signal of the block, or at a 3 % stop checked on 1m bars
(a gap below the stop fills at the open); after a stop there is no re-entry until the signal block has ended (the same
convention that produced the pre-registered development + validation numbers). Costs from the project's own cost
functions: CFD (spread), CFD x4, perp (taker fee + slippage + funding while held).

``--period devval`` reproduces the pre-registered development + validation figures (a check of this script);
``--period test`` opens the sealed test period ONCE: it refuses to run if ``data/research/cs_sealed_test.json`` exists,
and the access is logged permanently by ``SplitGuard`` before any data is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edge_lab as el  # noqa: E402

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account  # noqa: E402
from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate  # noqa: E402
from arven.core.config import CostsConfig, load_config  # noqa: E402
from arven.core.features_config import load_features_config  # noqa: E402
from arven.core.splitguard import BacktestPeriod  # noqa: E402
from arven.runs import load_inputs, make_guard  # noqa: E402

Z, OZ, HOLD_H, STOP = -1.5, 1.0, 24, 0.03
OUT = Path("data/research/cs_sealed_test.json")


def windows(period: str):
    app, fcfg = load_config(), load_features_config()
    guard = make_guard(app)
    if period == "test":
        return app, fcfg, [guard.resolve(BacktestPeriod.TEST, allow_sealed=True,
                                         reason="Crowded Shorts final evaluation, pre-registered in docs/strategy_crowded_shorts.md (owner's go 2026-10-11)")]
    return app, fcfg, [guard.resolve(BacktestPeriod.DEVELOPMENT), guard.resolve(BacktestPeriod.VALIDATION)]


def load(period: str):
    app, fcfg, ws = windows(period)
    parts = [load_inputs(app, fcfg, w) for w in ws]
    t = np.concatenate([p.features.t_ms for p in parts])
    names = parts[0].features.names
    vals = np.vstack([p.features.values for p in parts])
    f = {n: vals[:, k] for k, n in enumerate(names)}
    m = {k: np.concatenate([getattr(p.market, k) for p in parts]) for k in ("time_ms", "open", "high", "low")}
    fund_t = np.concatenate([p.market.funding_time_ms for p in parts]); fund_r = np.concatenate([p.market.funding_rate for p in parts])
    return app, ws, t, f, m, fund_t, fund_r


def trades_from_signals(t, f):
    z = np.nan_to_num(f["fund_z"], nan=0.0)
    oz = np.nan_to_num(f["oi_z"], nan=-9.0)
    pos = el.hold(((z <= Z) & (oz >= OZ)).astype(float), HOLD_H)
    starts = np.flatnonzero((pos != 0) & (np.concatenate([[0.0], pos[:-1]]) == 0))
    out = []
    for s in starts:
        e = s
        while e < len(pos) and pos[e] != 0:
            e += 1
        out.append((int(t[s]), int(t[e]) if e < len(t) else None))  # entry at the open at t[s]; planned exit at the open at t[e]
    return out


def simulate(blocks, m, fund_t, fund_r, costs: CostsConfig, stress: bool, perp: bool):
    T, O, Hh, L = m["time_ms"], m["open"], m["high"], m["low"]
    fee = taker_fee_rate(costs)
    res = []
    for t0, t1 in blocks:
        i0 = int(np.searchsorted(T, t0))
        if i0 >= len(T) or T[i0] != t0 or t1 is None:
            continue  # missing entry bar or the block runs past the data: no trade
        i1 = int(np.searchsorted(T, t1))
        if i1 >= len(T):
            continue
        sig = slippage_fraction(O[i0], Hh[i0], L[i0], costs, stress)
        entry = adverse_price(O[i0], 1, sig)
        stop = entry * (1 - STOP)
        hit = np.flatnonzero(L[i0:i1] <= stop)
        if hit.size:
            j = i0 + int(hit[0])
            ref, reason, exit_t = min(stop, O[j]), "STOP", int(T[j])
            sx = slippage_fraction(O[j], Hh[j], L[j], costs, stress)
        else:
            j = i1
            ref, reason, exit_t = O[i1], "TIME", int(T[i1])
            sx = slippage_fraction(O[j], Hh[j], L[j], costs, stress)
        exit_ = adverse_price(ref, -1, sx)
        pnl = exit_ - entry - fee * (entry + exit_)
        if perp:
            fm = (fund_t > t0) & (fund_t <= exit_t) & np.isfinite(fund_r)  # long pays positive / receives negative funding
            pnl -= float(np.sum(fund_r[fm])) * entry
        risk = entry - stop
        res.append({"entry_ms": t0, "exit_ms": exit_t, "entry": entry, "exit": exit_, "reason": reason, "ret": pnl / entry, "r": pnl / risk, "risk": risk})
    return res


def summary(res):
    if not res:
        return {"trades": 0}
    r = np.array([x["r"] for x in res]); ret = np.array([x["ret"] for x in res])
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    eq = np.cumprod(1 + ret)
    acc = summarize_account(replay_account([TradeForAccount(x["risk"], x["r"]) for x in res]), AccountRules())
    return {"trades": len(r), "win_rate": float(np.mean(r > 0)), "mean_r": float(r.mean()), "total_r": float(r.sum()),
            "profit_factor": float(wins / losses) if losses > 0 else float("inf"), "avg_trade_pct": float(100 * ret.mean()),
            "worst_trade_pct": float(100 * ret.min()), "compounded_1x_pct": float(100 * (eq[-1] - 1)),
            "max_dd_1x_pct": float(100 * np.max(1 - eq / np.maximum.accumulate(eq))), "stops": int(sum(x["reason"] == "STOP" for x in res)),
            "account_1000_at_1pct": acc}


def random_control(blocks, t, m, fund_t, fund_r, costs, draws=2000):
    lens = [((b - a) // el.H) for a, b in blocks if b is not None]
    hours = t[(t >= t[0]) & (t <= t[-1] - 30 * el.DAY)]
    rng = np.random.default_rng(7)
    means = []
    for _ in range(draws):
        rb = []
        for L in lens:
            a = int(rng.choice(hours))
            rb.append((a, a + int(L) * el.H))
        res = simulate(rb, m, fund_t, fund_r, costs, False, False)
        means.append(float(np.mean([x["r"] for x in res])) if res else np.nan)
    a = np.array(means)
    return {"draws": draws, "mean": float(np.nanmean(a)), "p95": float(np.nanpercentile(a, 95)), "p99": float(np.nanpercentile(a, 99))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=("devval", "test"), required=True)
    args = ap.parse_args()
    if args.period == "test" and OUT.exists():
        raise SystemExit(f"{OUT} exists: the sealed test has already been evaluated once; not re-running")
    cfd = CostsConfig.model_validate(yaml.safe_load(Path("config/costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))
    app, ws, t, f, m, fund_t, fund_r = load(args.period)
    blocks = trades_from_signals(t, f)
    report = {
        "cfd": summary(simulate(blocks, m, fund_t, fund_r, cfd, False, False)),
        "cfd_x4": summary(simulate(blocks, m, fund_t, fund_r, cfd, True, False)),
        "perp": summary(simulate(blocks, m, fund_t, fund_r, app.costs, False, True)),
    }
    trades = simulate(blocks, m, fund_t, fund_r, cfd, False, False)
    c = report["cfd"]
    verdict = None
    if args.period == "test":
        ok = c.get("trades", 0) > 0 and c["total_r"] > 0 and c["profit_factor"] >= 1.2 and report["cfd_x4"].get("total_r", -1) > 0
        verdict = "CONFIRMED" if ok else "NOT CONFIRMED"
    O = m["open"]
    out = {
        "strategy": "crowded_shorts", "period": args.period, "windows": [[w.start_ms, w.end_ms] for w in ws],
        "rules": {"fund_z_max": Z, "oi_z_min": OZ, "hold_hours": HOLD_H, "stop": STOP},
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip(),
        "git_dirty": bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False).stdout.strip()),
        "spec_sha256": hashlib.sha256(Path("docs/strategy_crowded_shorts.md").read_bytes()).hexdigest(),
        "report": report, "buy_and_hold_pct": float(100 * (O[-1] / O[0] - 1)),
        "random_entry_control_cfd": random_control(blocks, t, m, fund_t, fund_r, cfd),
        "verdict": verdict, "trades": trades,
    }
    for k, v in report.items():
        print(k, {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "account_1000_at_1pct"})
    print("account $1000 @1% (CFD):", {k: round(v, 2) if isinstance(v, float) else v for k, v in c.get("account_1000_at_1pct", {}).items()})
    print("buy&hold %+.1f%%" % out["buy_and_hold_pct"], "| random control", out["random_entry_control_cfd"], "| verdict:", verdict)
    path = OUT if args.period == "test" else OUT.with_name("cs_devval_check.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("written", path)


if __name__ == "__main__":
    main()
