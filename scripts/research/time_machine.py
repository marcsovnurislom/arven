"""H4 time machine: build the replay files of ``config/time_machine.yaml`` (``arven.time_machine``).

For each scenario: the 15m candles of the window (plus a few days of context shown from the start), and for every
strategy with trades entered in the window its timeline (setup / fill / targets / stop moves / close / result with the
$1000 account). Trades come unchanged from the exported trades (``scripts/strategy_trades_export.py``, which records
every trade's tracked events), so every number equals the Strategies page. A window touching the sealed test period
is refused; any look-ahead problem stops the build. Writes ``<research root>/research/time_machine/<id>.json`` and
``index.json`` (BTC under ``data/``, gold under ``data/markets/XAUUSD/``).

Usage: PYTHONPATH=src python scripts/research/time_machine.py [scenario_id ...]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml

from arven.backtest.account_sim import AccountRules
from arven.core.config import load_config
from arven.data.reader import open_readonly
from arven.event_moves import load_bars
from arven.time_machine import check_no_lookahead, overlaps, scenario_timeline

TF_MS = 15 * 60_000
CONTEXT_MS = 3 * 86_400_000  # candles before the start, shown at once so the first frame is not empty
TAIL_MS = 6 * 3_600_000  # candles after the last event
MAX_HOLD_AFTER_MS = 30 * 86_400_000  # a trade must close within 30 days after the window, or it is left out
PERIOD_FILES = ("development", "validation", "forward")  # never the sealed test, never Crowded Shorts' devval
SKIP = ("crowded_shorts",)
MARKETS = {
    "btc": {"instrument": None, "symbols": ("BTCUSDT",), "rules": AccountRules(), "unit": "BTC"},
    "gold": {"instrument": "XAUUSD", "symbols": ("XAUUSD", "XAUUSDT"), "rules": AccountRules(min_lot=1.0, lot_step=1.0), "unit": "oz"},
}


def ms(d) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def research_root(market: str) -> Path:
    app = load_config(instrument=MARKETS[market]["instrument"])
    return app.data.data_dir if MARKETS[market]["instrument"] is None else app.market_root


def strategy_trades(market: str) -> tuple[dict[str, list[dict]], dict[str, str]]:
    root = research_root(market) / "strategy_trades"
    trades: dict[str, list[dict]] = {}
    titles: dict[str, str] = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in SKIP):
        for period in PERIOD_FILES:
            f = d / f"{period}.json"
            if f.exists():
                payload = json.loads(f.read_text(encoding="utf-8"))
                trades.setdefault(d.name, []).extend(payload["trades"])
                titles[d.name] = payload.get("title", d.name)
    return trades, titles


def candles(con: duckdb.DuckDBPyConnection, symbols: tuple[str, ...], lo_ms: int, hi_ms: int) -> list[list[float]]:
    b = load_bars(con, symbols)
    keep = (b.open_time_ms >= lo_ms) & (b.open_time_ms < hi_ms)
    return [[int(t), round(float(o), 6), round(float(h), 6), round(float(lo), 6), round(float(c), 6)]
            for t, o, h, lo, c in zip(b.open_time_ms[keep], b.open[keep], b.high[keep], b.low[keep], b.close[keep], strict=True)]


def open_db(app):
    for _ in range(120):
        try:
            return open_readonly(app.data.database_path)
        except duckdb.IOException:  # the live process holds the file for a moment
            time.sleep(10)
    return open_readonly(app.data.database_path)


def main() -> None:
    wanted = set(sys.argv[1:])
    scenarios = yaml.safe_load(Path("config/time_machine.yaml").read_text(encoding="utf-8"))["scenarios"]
    app = load_config()
    test = app.splits.test
    test_lo, test_hi = int(test.start.timestamp() * 1000), int(test.end.timestamp() * 1000)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or None
    loaded = {m: strategy_trades(m) for m in MARKETS}
    index: dict[str, list[dict]] = {m: [] for m in MARKETS}
    for sc in scenarios:
        market = sc["market"]
        start, end = ms(sc["start"]), ms(sc["end"])
        trades, titles = loaded[market]
        tl = scenario_timeline(trades, start, end, MARKETS[market]["rules"], max_exit_ms=end + MAX_HOLD_AFTER_MS)
        last = max([end] + [v["last_t"] for v in tl.values()])
        if overlaps(start - CONTEXT_MS, last + TAIL_MS, test_lo, test_hi):
            raise SystemExit(f"{sc['id']}: the window touches the sealed test period - refused")
        for sid, v in tl.items():
            problems = check_no_lookahead(v["items"])
            if problems:
                raise SystemExit(f"{sc['id']} {sid}: look-ahead problems: {problems[:3]}")
            v["title"] = titles.get(sid, sid)
        entry = {"id": sc["id"], "market": market, "title": sc["title"], "about": sc["about"], "start_ms": start, "end_ms": end,
                 "strategies": {sid: {"title": v["title"], "trades": v["trades"], "final_equity": v["final_equity"], "total_r": v["total_r"]} for sid, v in tl.items()}}
        index[market].append(entry)
        if wanted and sc["id"] not in wanted:
            continue
        mapp = load_config(instrument=MARKETS[market]["instrument"])
        con = open_db(mapp)
        try:
            bars = candles(con, MARKETS[market]["symbols"], start - CONTEXT_MS, last + TAIL_MS)
        finally:
            con.close()
        payload = entry | {
            "tf_ms": TF_MS, "context_until_ms": start, "unit": MARKETS[market]["unit"], "candles": bars,
            "account_rules": {"start_equity": MARKETS[market]["rules"].start_equity, "risk_fraction": MARKETS[market]["rules"].risk_fraction},
            "timelines": tl, "git_commit": commit, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "note": "trades exactly as on the Strategies page; every item appears at the moment it became known; candles at their close",
        }
        out = research_root(market) / "research" / "time_machine"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{sc['id']}.json").write_text(json.dumps(payload), encoding="utf-8")
        print(f"{sc['id']:20s} {len(bars):6d} candles  " + "  ".join(f"{sid} {v['trades']} tr -> ${v['final_equity']:.2f}" for sid, v in tl.items()), flush=True)
    for market, entries in index.items():
        out = research_root(market) / "research" / "time_machine"
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    print("index written")


if __name__ == "__main__":
    main()
