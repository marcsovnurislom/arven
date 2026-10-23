"""Learning from mistakes: in which circumstances each strategy loses or wins (``arven.trade_context``).

Every exported trade (``scripts/strategy_trades_export.py``: development, validation, development+validation and
forward - never the sealed test) gets the circumstances known at its entry; the report compares each circumstance with
the strategy's other trades, separately for the history (development + validation) and the forward period, plus all
strategies of a market together. Flags need >= 30 trades and a Bonferroni-corrected bootstrap interval; a flag is an
idea to check on fresh data, never a change. Writes ``<research root>/research/mistakes.json`` (BTC under ``data/``,
gold under ``data/markets/XAUUSD/``) with the git commit and the time it was built.

Usage: PYTHONPATH=src python scripts/research/mistakes.py
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from arven.core.config import load_config
from arven.core.macro_config import load_macro_events
from arven.data.reader import open_readonly
from arven.trade_context import FEATURES, context_at, load_tf_bars, report

H1, H4 = 3_600_000, 4 * 3_600_000
HISTORY = ("development", "validation", "devval")
MARKETS = {"btc": (None, ("BTCUSDT",)), "gold": ("XAUUSD", ("XAUUSD", "XAUUSDT"))}


def research_root(instrument: str | None) -> Path:
    app = load_config(instrument=instrument)
    return app.data.data_dir if instrument is None else app.market_root


def open_db(app):
    for _ in range(120):
        try:
            return open_readonly(app.data.database_path)
        except duckdb.IOException:  # the live process holds the file for a moment
            time.sleep(10)
    return open_readonly(app.data.database_path)


def main() -> None:
    events = load_macro_events()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or None
    for market, (instrument, symbols) in MARKETS.items():
        app = load_config(instrument=instrument)
        con = open_db(app)
        try:
            h1, h4 = load_tf_bars(con, symbols, "1h", H1), load_tf_bars(con, symbols, "4h", H4)
        finally:
            con.close()
        root = research_root(instrument)
        rows: dict[str, list[dict]] = {}
        titles: dict[str, str] = {}
        for d in sorted(p for p in (root / "strategy_trades").iterdir() if p.is_dir()):
            for period in (*HISTORY, "forward"):
                f = d / f"{period}.json"
                if not f.exists():
                    continue
                payload = json.loads(f.read_text(encoding="utf-8"))
                titles[d.name] = payload.get("title", d.name)
                for x in payload["trades"]:
                    ctx = context_at(int(x["entry_time_ms"]), int(x["side"]), float(x["entry"]), float(x["stop"]), h1, h4, events)
                    rows.setdefault(d.name, []).append(ctx | {"net_r": float(x["net_r"]), "period": "forward" if period == "forward" else "history",
                                                              "entry_time_ms": int(x["entry_time_ms"])})
        out = {"market": market, "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "git_commit": commit, "features": list(FEATURES),
               "note": "circumstances known at each entry; flags need >= 30 trades and a corrected interval - ideas to test on fresh data, not changes",
               "strategies": {}, "proposals": []}
        everything = [r for rs in rows.values() for r in rs]
        for sid, rs in [*sorted(rows.items()), ("all", everything)]:
            hist = [r for r in rs if r["period"] == "history"]
            fwd = [r for r in rs if r["period"] == "forward"]
            out["strategies"][sid] = {"title": titles.get(sid, "All strategies together"), "history": report(hist) if hist else None,
                                      "forward": report(fwd) if fwd else None}
            for part, rep in (("history", out["strategies"][sid]["history"]), ("forward", out["strategies"][sid]["forward"])):
                for feat, cells in (rep or {}).get("features", {}).items():
                    for value, c in cells.items():
                        if c["flag"]:
                            out["proposals"].append({"strategy": sid, "part": part, "feature": feat, "value": value, "flag": c["flag"],
                                                     "trades": c["trades"], "mean_r": c["mean_r"], "rest_mean_r": rep["mean_r"],
                                                     "diff_low": c["diff_low"], "diff_high": c["diff_high"]})
        path = root / "research" / "mistakes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"{market}: {sum(len(v) for v in rows.values())} trades in {len(rows)} strategies; flags: {len(out['proposals'])} -> {path}")
        for p in out["proposals"]:
            print(f"   {p['flag']:6s} {p['strategy']:20s} {p['part']:8s} {p['feature']:10s} {p['value']:28s} n={p['trades']:3d} "
                  f"mean {p['mean_r']:+.2f}R  diff [{p['diff_low']:+.2f}, {p['diff_high']:+.2f}]")


if __name__ == "__main__":
    main()
