"""Stage 2 (wide) of the S7 fit: stop and take-profit in ATR of the setup's timeframe (stop 0.5 ... 3 ATR, take-profit
0.1 ... 6 ATR), holding time, detector variant x entry, and one or two filters (trend 1d / 4h, the owner's "earlier
extreme", SMC zones, volatility, touches, leg size, RSI(2) / RSI(14) at the fill in the trade's direction - the Connors
pullback idea - and ADX). Every combination is scored on 2020-01 -> 2025-01 with costs; the best ones are re-scored one
trade at a time and then once on the new data (2026-07 -> now).

Selection (the owner's constraints: win rate >= 70 %, profit, >= 3 trades a month, >= 2 on 1h):
  A "fit"    - the largest total R on development + validation together;
  B "stable" - the constraints met on development AND on validation separately; the largest of the two totals' minimum;
  C "global" - one rule for all nine markets with history (pooled), constraints on the pool and >= 3 a month per market.

Usage: PYTHONPATH=src python scripts/research/s7_fit_search2.py [INSTRUMENT ...]   (no argument: all, plus the global rule)
Output: data/s7_fit/search2_<INSTRUMENT>.json, data/s7_fit/search2_global.json
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s7_fit_search import NEVER, OUT, one_at_a_time  # noqa: E402

HISTORY = ["BTCUSDT", "XAUUSD", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]
FORWARD_OF = {"XAUUSD": "XAUUSDT"}
STOP_K = (0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0)
MIN_WIN = 0.70
TOP = 15
GLOBAL_PER_MONTH = 4.0  # the one-rule strategy over all markets: the owner's "3-4 signals a month" for the whole strategy

SINGLE = {
    "trend1d+": lambda d: d["f_trend_1d"] > 0, "trend1d-": lambda d: d["f_trend_1d"] < 0,
    "trend4h+": lambda d: d["f_trend_4h"] > 0, "trend4h-": lambda d: d["f_trend_4h"] < 0,
    "no_earlier": lambda d: d["f_earlier_extreme"] < 0.5, "smc1": lambda d: d["f_smc"] >= 1, "smc2": lambda d: d["f_smc"] >= 2,
    "vol_lo": lambda d: d["f_vol_pct"] <= 0.5, "vol_hi": lambda d: d["f_vol_pct"] > 0.5,
    "touch4": lambda d: d["f_touches"] >= 4, "leg_big": lambda d: d["f_leg_atr"] >= 3.5, "leg_small": lambda d: d["f_leg_atr"] < 3.5,
    "rsi2<10": lambda d: d["f_rsi2_fill"] < 10, "rsi2<25": lambda d: d["f_rsi2_fill"] < 25, "rsi14<40": lambda d: d["f_rsi14_fill"] < 40,
    "rsi14<50": lambda d: d["f_rsi14_fill"] < 50, "adx>25": lambda d: d["f_adx_fill"] > 25, "adx<20": lambda d: d["f_adx_fill"] < 20,
    "long": lambda d: d["side"] == 1, "short": lambda d: d["side"] == -1,
}


def load(instrument: str, periods: list[str]) -> dict | None:
    parts = [np.load(OUT / f"{instrument}_{p}.npz", allow_pickle=False) for p in periods if (OUT / f"{instrument}_{p}.npz").exists()]
    if not parts:
        return None
    keys = [k for k in parts[0].files if k not in ("levels", "horizons", "cost_side_bps", "months", "atr_levels")]
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    out["period_id"] = np.concatenate([np.full(len(p["side"]), i) for i, p in enumerate(parts)])
    out["L"], out["horizons"] = parts[0]["atr_levels"], parts[0]["horizons"]
    out["cost_side_bps"] = float(parts[0]["cost_side_bps"])
    out["months_each"] = [float(p["months"]) for p in parts]
    out["months"] = float(sum(out["months_each"]))
    return out


def filters() -> dict:
    out = {"all": lambda d: np.ones(len(d["side"]), dtype=bool)} | SINGLE
    for (a, fa), (b, fb) in itertools.combinations(SINGLE.items(), 2):
        out[f"{a}&{b}"] = (lambda fa, fb: lambda d: fa(d) & fb(d))(fa, fb)
    return out


FILTERS = filters()


def matrix(d: dict, rows: np.ndarray, ks: int, hi: int) -> tuple[np.ndarray, np.ndarray]:
    """Net R (rows x take-profit levels) for a stop of STOP_K[ks] ATR and a time exit after horizons[hi] minutes, and
    the exit minute of each cell."""
    k = STOP_K[ks]
    ki = int(round(k * 10)) - 1  # ATR level index of the stop
    sl = d["adv_atr"][rows, ki]
    tp = d["fav_atr"][rows, :]
    unit = d["unit_atr"][rows]
    fill = d["fill"][rows]
    side = d["side"][rows]
    hmin = int(d["horizons"][hi])
    tp_hit = (tp < sl[:, None]) & (tp <= hmin)
    sl_hit = (sl[:, None] <= tp) & (sl[:, None] <= hmin)
    r_time = ((d["close_at"][rows, hi] - fill) * side / (k * unit))[:, None]
    r = np.where(tp_hit, d["L"][None, :] / k, np.where(sl_hit, -1.0, r_time))
    c = d["cost_side_bps"]
    c = c[rows] if isinstance(c, np.ndarray) else c  # per row in the all-markets pool
    cost = (2 * c / 1e4 * fill / (k * unit))[:, None]
    minutes = np.where(tp_hit, tp, np.where(sl_hit, sl[:, None], hmin))
    return r - cost, minutes


def exact(d: dict, rows: np.ndarray, ks: int, hi: int, li: int) -> dict:
    """One trade at a time for one cell; per period part too."""
    r, minutes = matrix(d, rows, ks, hi)
    r, minutes = r[:, li], minutes[:, li]
    ok = np.isfinite(r)
    rows, r, minutes = rows[ok], r[ok], minutes[ok]
    keep = one_at_a_time(d["fill_ms"][rows], d["fill_ms"][rows] + minutes.astype(np.int64) * 60_000)
    rows, r = rows[keep], r[keep]
    res = {"trades": int(len(r)), "win": float(np.mean(r > 0)) if len(r) else 0.0, "total_r": float(r.sum()),
           "mean_r": float(r.mean()) if len(r) else 0.0, "per_month": len(r) / d["months"]}
    res["parts"] = [{"trades": int((d["period_id"][rows] == i).sum()), "total_r": float(r[d["period_id"][rows] == i].sum()),
                     "win": float(np.mean(r[d["period_id"][rows] == i] > 0)) if (d["period_id"][rows] == i).any() else 0.0}
                    for i in range(len(d["months_each"]))]
    return res


def candidates(d: dict) -> list[dict]:
    """Every cell meeting the win / profit / frequency bar on the pooled fit window (no overlap rule yet), best first."""
    out = []
    for var in sorted(set(d["variant"].tolist())):
        per_month = 2.0 if var.startswith("1h") else 3.0
        need = per_month * d["months"]
        for entry in ("E1", "E2", "E3"):
            base = (d["variant"] == var) & (d["entry"] == entry) & np.isfinite(d["unit_atr"]) & (d["unit_atr"] > 0)
            for fname, ffn in FILTERS.items():
                rows = np.flatnonzero(base & ffn(d))
                if len(rows) < need:
                    continue
                for ks in range(len(STOP_K)):
                    for hi in range(len(d["horizons"])):
                        r, _ = matrix(d, rows, ks, hi)
                        win = np.mean(r > 0, axis=0)
                        tot = np.nansum(r, axis=0)
                        good = np.flatnonzero((win >= MIN_WIN) & (tot > 0))
                        for li in good:
                            out.append({"variant": var, "entry": entry, "filter": fname, "ks": ks, "hi": hi, "li": int(li),
                                        "pre_total": float(tot[li]), "pre_win": float(win[li]), "need": need})
    out.sort(key=lambda c: -c["pre_total"])
    return out


def describe(d: dict, c: dict) -> dict:
    return {"variant": c["variant"], "entry": c["entry"], "filter": c["filter"], "stop_atr": STOP_K[c["ks"]],
            "tp_atr": float(d["L"][c["li"]]), "tp_r": float(d["L"][c["li"]] / STOP_K[c["ks"]]), "hold_min": int(d["horizons"][c["hi"]])}


def rows_for(d: dict, c: dict) -> np.ndarray:
    return np.flatnonzero((d["variant"] == c["variant"]) & (d["entry"] == c["entry"]) & np.isfinite(d["unit_atr"]) & (d["unit_atr"] > 0)
                          & FILTERS[c["filter"]](d))


def search_market(instrument: str) -> dict:
    d = load(instrument, ["development", "validation"])
    if d is None:
        return {}
    fwd = load(FORWARD_OF.get(instrument, instrument), ["forward"])
    cands = candidates(d)
    picks: dict = {"fit": None, "stable": None}
    checked = 0
    for c in cands[:4000]:  # the pre-scored best; the overlap rule only lowers counts
        ex = exact(d, rows_for(d, c), c["ks"], c["hi"], c["li"])
        checked += 1
        if ex["trades"] < c["need"] or ex["win"] < MIN_WIN or ex["total_r"] <= 0:
            continue
        cand = describe(d, c) | {"fit": ex, "_c": c}
        if picks["fit"] is None or ex["total_r"] > picks["fit"]["fit"]["total_r"]:
            picks["fit"] = cand
        parts = ex["parts"]
        if all(p["total_r"] > 0 and p["win"] >= MIN_WIN for p in parts):
            key = min(p["total_r"] for p in parts)
            if picks["stable"] is None or key > min(p["total_r"] for p in picks["stable"]["fit"]["parts"]):
                picks["stable"] = cand
    for name, p in picks.items():
        if p and fwd is not None:
            c = p.pop("_c")
            p["new_data"] = exact(fwd, rows_for(fwd, c), c["ks"], c["hi"], c["li"]) | {"months": fwd["months"]}
        elif p:
            p.pop("_c")
    out = {"instrument": instrument, "candidates": len(cands), "checked": checked, **picks}
    (OUT / f"search2_{instrument}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return out


def fmt(p: dict | None) -> str:
    if not p:
        return "none meets the bar"
    f, n = p["fit"], p.get("new_data")
    s = (f"{p['variant']} {p['entry']} [{p['filter']}] stop {p['stop_atr']} ATR, TP {p['tp_atr']} ATR ({p['tp_r']:.2f} R), hold {p['hold_min']}m"
         f" | fit {f['trades']} tr ({f['per_month']:.1f}/mo) win {f['win']:.0%} {f['total_r']:+.1f}R")
    if n:
        s += f" | NEW {n['trades']} tr win {n['win']:.0%} {n['total_r']:+.1f}R"
    return s


def main() -> None:
    if sys.argv[1:] == ["--global"]:
        g = search_global()
        b = g.get("best")
        print("GLOBAL:", g.get("candidates"), "cells;", "none meets the bar" if not b else
              f"{fmt(b)} | per market/month {b['fit']['per_month_per_market']:.1f} | markets + {b['fit']['markets_positive']}"
              + (f" | NEW markets + {b['new_data']['markets_positive']}" if b.get("new_data") else ""), flush=True)
        return
    for inst in sys.argv[1:] or HISTORY:
        o = search_market(inst)
        print(f"{inst}: {o.get('candidates')} cells pass pre-score\n  A fit:    {fmt(o.get('fit'))}\n  B stable: {fmt(o.get('stable'))}", flush=True)


# --- C: one rule for every market -----------------------------------------------------------------------------------

def load_all(periods: list[str], markets: list[str]) -> dict | None:
    parts = []
    for mi, inst in enumerate(markets):
        x = load(inst, periods)
        if x is None:
            continue
        x["market_id"] = np.full(len(x["side"]), mi)
        x["cost_row"] = np.full(len(x["side"]), x.pop("cost_side_bps"))
        parts.append(x)
    if not parts:
        return None
    keys = [k for k in parts[0] if isinstance(parts[0][k], np.ndarray) and k not in ("L", "horizons")]
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    out["L"], out["horizons"] = parts[0]["L"], parts[0]["horizons"]
    out["months_each"] = parts[0]["months_each"]
    out["months"] = parts[0]["months"]  # per market (every market covers the same window)
    out["n_markets"] = len(parts)
    out["cost_side_bps"] = out["cost_row"]  # per row: matrix() broadcasts it
    return out


def exact_global(d: dict, rows: np.ndarray, ks: int, hi: int, li: int) -> dict:
    r, minutes = matrix(d, rows, ks, hi)
    r, minutes = r[:, li], minutes[:, li]
    ok = np.isfinite(r)
    rows, r, minutes = rows[ok], r[ok], minutes[ok]
    keep = np.zeros(len(rows), dtype=bool)
    for m in np.unique(d["market_id"][rows]):  # one trade at a time per market
        sel = np.flatnonzero(d["market_id"][rows] == m)
        keep[sel] = one_at_a_time(d["fill_ms"][rows][sel], d["fill_ms"][rows][sel] + minutes[sel].astype(np.int64) * 60_000)
    rows, r = rows[keep], r[keep]
    per_market = {int(m): float(r[d["market_id"][rows] == m].sum()) for m in np.unique(d["market_id"][rows])}
    return {"trades": int(len(r)), "win": float(np.mean(r > 0)) if len(r) else 0.0, "total_r": float(r.sum()),
            "mean_r": float(r.mean()) if len(r) else 0.0, "per_month_per_market": len(r) / d["months"] / d["n_markets"],
            "markets_positive": sum(v > 0 for v in per_market.values()), "per_market_r": per_market,
            "parts": [{"total_r": float(r[d["period_id"][rows] == i].sum()), "win": float(np.mean(r[d["period_id"][rows] == i] > 0))
                       if (d["period_id"][rows] == i).any() else 0.0} for i in range(len(d["months_each"]))]}


def search_global() -> dict:
    d = load_all(["development", "validation"], HISTORY)
    fwd = load_all(["forward"], [FORWARD_OF.get(m, m) for m in HISTORY] + ["XAGUSDT", "EURUSD", "GBPUSD"])
    d["months"] *= 1  # per market
    cands = []
    for var in sorted(set(d["variant"].tolist())):
        need = GLOBAL_PER_MONTH * d["months"]  # the strategy as a whole (all markets together): >= 4 signals a month
        for entry in ("E1", "E2", "E3"):
            base = (d["variant"] == var) & (d["entry"] == entry) & np.isfinite(d["unit_atr"]) & (d["unit_atr"] > 0)
            for fname, ffn in FILTERS.items():
                rows = np.flatnonzero(base & ffn(d))
                if len(rows) < need:
                    continue
                for ks in range(len(STOP_K)):
                    for hi in range(len(d["horizons"])):
                        r, _ = matrix(d, rows, ks, hi)
                        win, tot = np.mean(r > 0, axis=0), np.nansum(r, axis=0)
                        for li in np.flatnonzero((win >= MIN_WIN) & (tot > 0)):
                            cands.append({"variant": var, "entry": entry, "filter": fname, "ks": ks, "hi": hi, "li": int(li),
                                          "pre_total": float(tot[li]), "need": need})
    cands.sort(key=lambda c: -c["pre_total"])
    best = None
    for c in cands[:3000]:
        ex = exact_global(d, rows_for(d, c), c["ks"], c["hi"], c["li"])
        if ex["trades"] < c["need"] or ex["win"] < MIN_WIN or ex["total_r"] <= 0:
            continue
        if not all(p["total_r"] > 0 and p["win"] >= MIN_WIN for p in ex["parts"]):
            continue
        if best is None or ex["total_r"] > best["fit"]["total_r"]:
            best = describe(d, c) | {"fit": ex, "_c": c}
    out = {"candidates": len(cands), "best": best}
    if best:
        c = best.pop("_c")
        fwd["months"] = fwd["months"]
        best["new_data"] = exact_global(fwd, rows_for(fwd, c), c["ks"], c["hi"], c["li"])
    (OUT / "search2_global.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
