"""Collect scripts/research/all_markets.py results (and the live forward records) into one table per period.

Applies the pre-registered reading rule of all_markets.py (supported = validation >= 30 trades, mean R > 0 and above
the random-entry control's 95th percentile, and development mean R > 0). Prints JSON lines and writes
data/research/all_markets_summary.json, which docs/ANALIZ_VSEH_STRATEGIY.md quotes.

Usage: PYTHONPATH=src python scripts/research/all_markets_report.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA = Path("data")
MARKETS = {  # research instrument -> (live record root, label)
    "BTCUSDT": (DATA, "BTC"), "XAUUSD": (DATA / "markets" / "XAUUSDT", "Gold"), "ETHUSDT": (DATA / "markets" / "ETHUSDT", "ETH"),
    "SOLUSDT": (DATA / "markets" / "SOLUSDT", "SOL"), "XRPUSDT": (DATA / "markets" / "XRPUSDT", "XRP"),
    "BNBUSDT": (DATA / "markets" / "BNBUSDT", "BNB"), "DOGEUSDT": (DATA / "markets" / "DOGEUSDT", "DOGE"),
    "ADAUSDT": (DATA / "markets" / "ADAUSDT", "ADA"), "LINKUSDT": (DATA / "markets" / "LINKUSDT", "LINK"),
    "XAGUSD": (DATA / "markets" / "XAGUSDT", "Silver"), "EURUSD": (DATA / "markets" / "EURUSD", "EUR/USD"),
    "GBPUSD": (DATA / "markets" / "GBPUSD", "GBP/USD"),
}


def research_dir(inst: str) -> Path:
    return DATA / "research" if inst == "BTCUSDT" else DATA / "markets" / inst / "research"


def load(inst: str, period: str) -> dict[str, Any] | None:
    p = research_dir(inst) / f"all_markets_{period}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def verdict(dev: dict | None, val: dict | None) -> str:
    if not dev or not val:
        return "no data"
    v, d, ctl = val["cost"], dev["cost"], val.get("control")
    if v["trades"] < 30:
        return "too few trades"
    ok = (v["mean_r"] or 0) > 0 and (d["mean_r"] or 0) > 0 and ctl is not None and v["mean_r"] > ctl["p95"]
    return "supported" if ok else "not supported"


def main() -> None:
    rows = []
    for inst, (live_root, label) in MARKETS.items():
        per = {p: load(inst, p) for p in ("development", "validation", "forward")}
        live = live_root / "paper" / "strategies_summary.json"
        fwd_live = json.loads(live.read_text(encoding="utf-8")).get("strategies", {}) if live.exists() else {}
        sids = sorted({s for p in per.values() if p for s in p["strategies"]} | set(fwd_live))
        for sid in sids:
            def cut(p: str) -> dict | None:
                d = per[p]
                return None if d is None or sid not in d["strategies"] else {k: v for k, v in d["strategies"][sid].items() if k != "trades"}
            dev, val, fwd = cut("development"), cut("validation"), cut("forward")
            lv = fwd_live.get(sid) or {}
            rows.append({"market": label, "instrument": inst, "strategy": sid, "development": dev, "validation": val, "forward_backtest": fwd,
                         "forward_live": {k: lv.get(k) for k in ("signals", "closed", "total_r", "mean_r", "win_rate")} | {"verdict": (lv.get("review") or {}).get("verdict")} if lv else None,
                         "verdict": verdict(dev, val),
                         "buy_and_hold_pct": {p: per[p]["buy_and_hold_pct"] for p in per if per[p]}})
    out = DATA / "research" / "all_markets_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows}, indent=1, default=float), encoding="utf-8")
    for r in rows:
        f = lambda d: "-" if not d else f"{d['cost']['trades']}/{d['cost']['total_r']:+.1f}R"  # noqa: E731
        print(f"{r['market']:8s} {r['strategy']:20s} dev {f(r['development']):>12s} val {f(r['validation']):>12s} fwd {f(r['forward_backtest']):>12s} -> {r['verdict']}")
    print("saved", out)


if __name__ == "__main__":
    main()
