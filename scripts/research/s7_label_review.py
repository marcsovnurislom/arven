"""The owner's verdicts on S7 trades (page "S7 trades", data/s7_study/trade_labels.json) against what the trades looked
like (2026-10-28). For every marked trade: its result and the geometry the owner commented on - touches and how close
together they are, the line's length and how far candles cross it between its anchors ("crooked line"), whether a more
extreme high / low stood just before the line's first anchor ("start from the earlier low"), how many bars passed from
the setup to the entry ("too many candles since the setup"), and the stop's distance. Descriptive only - 44 verdicts are
far too few to fit a rule on; the output is the input for S7 v2 rules, each of which must then be checked on its own.

Usage: PYTHONPATH=src python scripts/research/s7_label_review.py   -> data/s7_study/label_review.json
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

import numpy as np

TF_MS = {"s7_trend_break_fib": 900_000, "s7_smc": 900_000, "s7_30m": 1_800_000, "s7_1h": 3_600_000, "s7_4h": 14_400_000, "s7_1d": 86_400_000}


def features(t: dict, model: str) -> dict:
    tf = TF_MS[model]
    c = t["candles"]
    times = np.array([x["t"] for x in c])
    hi, lo = np.array([x["h"] for x in c]), np.array([x["l"] for x in c])
    rng = float(np.median(hi - lo)) or 1e-12
    (a, b) = t["line"]["points"]
    slope = (b["price"] - a["price"]) / max(1, (b["timeMs"] - a["timeMs"]))
    at = lambda ms: a["price"] + slope * (ms - a["timeMs"])  # noqa: E731
    side = t["side"]
    # the line is drawn on highs for a long (a falling resistance broken upward) and on lows for a short
    inside = (times > a["timeMs"]) & (times < b["timeMs"])
    pierce = hi[inside] - np.array([at(x) for x in times[inside]]) if side == 1 else np.array([at(x) for x in times[inside]]) - lo[inside]
    touches = sorted(p["timeMs"] for p in t["touches"])
    gaps = [(y - x) / tf for x, y in zip(touches, touches[1:])]
    before = (times < a["timeMs"]) & (times >= a["timeMs"] - 60 * tf)
    earlier_extreme = bool(before.any() and ((hi[before].max() > a["price"]) if side == 1 else (lo[before].min() < a["price"])))
    return {
        "net_r": t["net_r"], "side": side, "touches": len(touches),
        "min_touch_gap_bars": min(gaps) if gaps else None, "touch_span_bars": (touches[-1] - touches[0]) / tf if touches else None,
        "line_bars": (b["timeMs"] - a["timeMs"]) / tf,
        "max_pierce_ranges": float(pierce.max() / rng) if len(pierce) else 0.0,
        "earlier_extreme_60_bars": earlier_extreme,
        "entry_delay_bars": (t["entry_time_ms"] - t["arm_time_ms"]) / tf,
        "setup_to_entry_bars": (t["entry_time_ms"] - b["timeMs"]) / tf,
        "stop_ranges": abs(t["entry"] - t["stop"]) / rng,
        "first_exit": t["exit_reasons"][0] if t["exit_reasons"] else "-",
    }


def main() -> None:
    labels = json.loads(Path("data/s7_study/trade_labels.json").read_text(encoding="utf-8"))
    files = list(Path("data/s7_study").glob("trades_s7_*_*.json")) + list(Path("data/markets").glob("*/s7_study/trades_s7_*_*.json"))
    rows = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for t in d["trades"]:
            if t["id"] in labels and not any(r["id"] == t["id"] for r in rows):
                rows.append({"id": t["id"], "market": d["instrument"], "model": d["model"], "period": d["period"],
                             "verdict": labels[t["id"]]["verdict"], "note": labels[t["id"]].get("note", ""), **features(t, d["model"])})
    out = {"n": len(rows), "rows": rows, "by_verdict": {}}
    keys = ["net_r", "touches", "min_touch_gap_bars", "touch_span_bars", "line_bars", "max_pierce_ranges", "entry_delay_bars",
            "setup_to_entry_bars", "stop_ranges"]
    for v in ("ok", "wrong", "unsure"):
        g = [r for r in rows if r["verdict"] == v]
        if not g:
            continue
        s = {"n": len(g), "total_r": sum(r["net_r"] for r in g), "win_rate": sum(r["net_r"] > 0 for r in g) / len(g),
             "earlier_extreme_share": sum(r["earlier_extreme_60_bars"] for r in g) / len(g)}
        for k in keys:
            vals = [r[k] for r in g if r[k] is not None]
            s[f"median_{k}"] = st.median(vals) if vals else None
        out["by_verdict"][v] = s
        print(v, json.dumps({k: (round(x, 2) if isinstance(x, float) else x) for k, x in s.items()}))
    Path("data/s7_study/label_review.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
