"""Stage 2 of the S7 fit (see s7_fit.py): per market, every combination of detector variant x entry x stop x take-profit
(0.1 ... 4.0 R) x holding time x one filter, scored on 2020-01 -> 2025-01 (development + validation together), one
trade at a time, costs included. Constraints (the owner's): win rate >= 70 %, total R > 0, >= 3 trades a month (>= 2 on
1h). Objective: the largest total R. The chosen combination is then scored once on the new data (2026-07 -> now).

Usage: PYTHONPATH=src python scripts/research/s7_fit_search.py [INSTRUMENT ...]  -> data/s7_fit/search_<INSTRUMENT>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

OUT = Path("data/s7_fit")
FORWARD_OF = {"XAUUSD": "XAUUSDT"}  # gold's history is Dukascopy XAUUSD; its new data is the live XAUUSDT feed
STOPS = ("S1", "S2", "S3")
MIN_WIN = 0.70
NEVER = np.iinfo(np.int64).max


def load(instrument: str, periods: list[str]) -> dict[str, np.ndarray] | None:
    parts = [np.load(OUT / f"{instrument}_{p}.npz", allow_pickle=False) for p in periods if (OUT / f"{instrument}_{p}.npz").exists()]
    if not parts:
        return None
    keys = [k for k in parts[0].files if k not in ("levels", "horizons", "cost_side_bps", "months")]
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    for st in STOPS:  # files written before the fix: "never reached" + 1 overflowed to a negative index -> never
        out[f"tp_{st}"] = np.where(out[f"tp_{st}"] < 0, NEVER, out[f"tp_{st}"])
    out["levels"], out["horizons"] = parts[0]["levels"], parts[0]["horizons"]
    out["cost_side_bps"] = float(parts[0]["cost_side_bps"])
    out["months"] = float(sum(float(p["months"]) for p in parts))
    return out


FILTERS: dict[str, callable] = {
    "none": lambda d: np.ones(len(d["side"]), dtype=bool),
    "trend_1d_with": lambda d: d["f_trend_1d"] > 0,
    "trend_4h_with": lambda d: d["f_trend_4h"] > 0,
    "trend_both_with": lambda d: (d["f_trend_1d"] > 0) & (d["f_trend_4h"] > 0),
    "trend_1d_against": lambda d: d["f_trend_1d"] < 0,
    "no_earlier_extreme": lambda d: d["f_earlier_extreme"] < 0.5,
    "smc_1plus": lambda d: d["f_smc"] >= 1,
    "smc_2plus": lambda d: d["f_smc"] >= 2,
    "vol_low": lambda d: d["f_vol_pct"] <= 0.5,
    "vol_high": lambda d: d["f_vol_pct"] > 0.5,
    "touches_4plus": lambda d: d["f_touches"] >= 4,
    "leg_big": lambda d: d["f_leg_atr"] >= np.nanmedian(d["f_leg_atr"]),
    "leg_small": lambda d: d["f_leg_atr"] < np.nanmedian(d["f_leg_atr"]),
    "long_only": lambda d: d["side"] == 1,
    "short_only": lambda d: d["side"] == -1,
}


def outcomes(d: dict, rows: np.ndarray, stop: str, li: int, hi: int) -> tuple[np.ndarray, np.ndarray]:
    """Net R and exit time of each row for a take-profit at levels[li] R and a time exit after horizons[hi] minutes."""
    tp = d[f"tp_{stop}"][rows, li]
    sl = d[f"sl_{stop}"][rows]
    risk = d[f"risk_{stop}"][rows]
    fill = d["fill"][rows]
    side = d["side"][rows]
    hmin = int(d["horizons"][hi])
    tp_hit = (tp < sl) & (tp <= hmin)
    sl_hit = (sl <= tp) & (sl <= hmin)
    r_time = (d["close_at"][rows, hi] - fill) * side / np.where(risk > 0, risk, np.nan)
    r = np.where(tp_hit, d["levels"][li], np.where(sl_hit, -1.0, r_time))
    cost = 2 * d["cost_side_bps"] / 1e4 * fill / np.where(risk > 0, risk, np.nan)
    minutes = np.where(tp_hit, tp, np.where(sl_hit, sl, hmin))
    exit_ms = d["fill_ms"][rows] + minutes.astype(np.int64) * 60_000
    return r - cost, exit_ms


def one_at_a_time(fill_ms: np.ndarray, exit_ms: np.ndarray) -> np.ndarray:
    order = np.argsort(fill_ms, kind="stable")
    keep = np.zeros(len(fill_ms), dtype=bool)
    free = -1
    for i in order:
        if fill_ms[i] >= free:
            keep[i] = True
            free = exit_ms[i]
    return keep


def score(d: dict, rows: np.ndarray, stop: str, li: int, hi: int) -> dict:
    r, ex_ms = outcomes(d, rows, stop, li, hi)
    ok = np.isfinite(r)
    rows, r, ex_ms = rows[ok], r[ok], ex_ms[ok]
    k = one_at_a_time(d["fill_ms"][rows], ex_ms)
    r = r[k]
    return {"trades": int(len(r)), "win": float(np.mean(r > 0)) if len(r) else 0.0, "total_r": float(r.sum()), "mean_r": float(r.mean()) if len(r) else 0.0}


def search(instrument: str) -> dict:
    d = load(instrument, ["development", "validation"])
    if d is None:
        return {}
    fwd = load(FORWARD_OF.get(instrument, instrument), ["forward"])
    best: dict | None = None
    tried = 0
    variants = sorted(set(d["variant"].tolist()))
    for var in variants:
        min_per_month = 2.0 if var.startswith("1h") else 3.0
        for entry in ("E1", "E2", "E3"):
            base = (d["variant"] == var) & (d["entry"] == entry)
            for fname, ffn in FILTERS.items():
                rows = np.flatnonzero(base & ffn(d))
                if len(rows) < min_per_month * d["months"]:
                    continue
                for stop in STOPS:
                    for hi in range(len(d["horizons"])):
                        for li in range(len(d["levels"])):
                            tried += 1
                            s = score(d, rows, stop, li, hi)
                            if s["trades"] < min_per_month * d["months"] or s["win"] < MIN_WIN or s["total_r"] <= 0:
                                continue
                            if best is None or s["total_r"] > best["fit"]["total_r"]:
                                best = {"variant": var, "entry": entry, "filter": fname, "stop": stop, "tp_r": float(d["levels"][li]),
                                        "hold_min": int(d["horizons"][hi]), "fit": s, "li": li, "hi": hi}
    out = {"instrument": instrument, "tried": tried, "months_fit": d["months"], "best": best}
    if best and fwd is not None:
        rows = np.flatnonzero((fwd["variant"] == best["variant"]) & (fwd["entry"] == best["entry"]) & FILTERS[best["filter"]](fwd))
        out["forward"] = score(fwd, rows, best["stop"], best["li"], best["hi"]) | {"months": fwd["months"]}
    (OUT / f"search_{instrument}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    for inst in sys.argv[1:]:
        o = search(inst)
        b = o.get("best")
        print(inst, "tried", o.get("tried"), "->", "nothing meets the constraints" if not b else
              f"{b['variant']} {b['entry']} {b['filter']} {b['stop']} TP {b['tp_r']}R hold {b['hold_min']}m | fit {b['fit']} | new data {o.get('forward')}", flush=True)
