"""Read-only data access for the ARVEN web API (docs/ARVEN_MASTER_PROMPT.md section 5.6).

Pure functions over explicit paths / an open read-only DuckDB connection: no FastAPI here, so every function is
testable with temporary files. Nothing in this module writes market data or touches any execution code (CLAUDE.md
rule 12); the only write path of the whole web layer is the manual trade journal (``arven.web.journal``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from arven.engine.signal_events import SignalUpdateKind
from arven.engine.signal_store import read_signals, read_updates

CANDLE_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
MAX_CANDLES = 2000


def read_candles(con: duckdb.DuckDBPyConnection, symbol: str, timeframe: str, limit: int = 500, before_ms: int | None = None) -> list[dict[str, Any]]:
    """Newest ``limit`` bars (ascending order) of ``timeframe`` strictly before ``before_ms`` (default: all)."""
    if timeframe not in CANDLE_TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {CANDLE_TIMEFRAMES}")
    limit = max(1, min(int(limit), MAX_CANDLES))
    bound = "" if before_ms is None else " AND open_time_ms < ?"
    args: list[Any] = [symbol] + ([] if before_ms is None else [int(before_ms)]) + [limit]
    if timeframe == "1m":
        sql = f"SELECT open_time_ms, open, high, low, close, volume, TRUE FROM ohlcv_1m WHERE symbol = ?{bound} ORDER BY open_time_ms DESC LIMIT ?"
    else:
        sql = (
            f"SELECT open_time_ms, open, high, low, close, volume, is_complete FROM ohlcv WHERE symbol = ? AND timeframe = '{timeframe}'"
            f"{bound} ORDER BY open_time_ms DESC LIMIT ?"
        )
    rows = con.execute(sql, args).fetchall()
    return [{"t": int(r[0]), "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5], "complete": bool(r[6])} for r in reversed(rows)]


def read_hourly_bars(con: duckdb.DuckDBPyConnection, symbol: str, since_ms: int) -> list[tuple]:
    """Completed stored 1h bars from ``since_ms``: ``(open_time_ms, open, high, low, close_time_ms)``, ascending."""
    return con.execute(
        "SELECT open_time_ms, open, high, low, close_time_ms FROM ohlcv WHERE symbol = ? AND timeframe = '1h' AND is_complete "
        "AND open_time_ms >= ? ORDER BY open_time_ms", [symbol, since_ms],
    ).fetchall()


def last_bar_time_ms(con: duckdb.DuckDBPyConnection, symbol: str) -> int | None:
    row = con.execute("SELECT max(open_time_ms) FROM ohlcv_1m WHERE symbol = ?", [symbol]).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def screener_row(con: duckdb.DuckDBPyConnection, symbol: str) -> dict[str, Any] | None:
    """The one configured symbol: last price, 24h change and 24h quote volume from stored 1h bars."""
    rows = con.execute(
        "SELECT open_time_ms, close, quote_volume FROM ohlcv WHERE symbol = ? AND timeframe = '1h' ORDER BY open_time_ms DESC LIMIT 25", [symbol],
    ).fetchall()
    if len(rows) < 2:
        return None
    last, first = rows[0], rows[-1]
    return {
        "symbol": symbol, "price": last[1], "change_24h_pct": (last[1] / first[1] - 1.0) * 100.0 if first[1] else None,
        "quote_volume_24h": sum(r[2] for r in rows[:24]), "as_of_ms": int(last[0]),
        "sparkline": [r[1] for r in reversed(rows)],
    }


def _signal_status(updates: list, entry_type: str = "market") -> str:
    """closed / cancelled (a resting entry withdrawn unfilled) / partial (a TP filled) / open / pending (a resting
    limit entry not filled yet)."""
    kinds = {u.kind for u in updates}
    if SignalUpdateKind.CLOSED in kinds:
        return "closed"
    if SignalUpdateKind.CANCELLED in kinds:
        return "cancelled"
    if SignalUpdateKind.TP_HIT in kinds:
        return "partial"
    if entry_type == "limit" and SignalUpdateKind.FILLED not in kinds:
        return "pending"
    return "open"


def list_signals(root: Path, strategy_ids: list[str], limit: int = 100, strategy: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid in strategy_ids if strategy is None else [strategy]:
        updates_by_id: dict[str, list] = {}
        for u in read_updates(root, sid):
            updates_by_id.setdefault(u.signal_id, []).append(u)
        for s in read_signals(root, sid):
            ups = updates_by_id.get(s.signal_id, [])
            out.append({**s.to_dict(), "entry_type": s.entry_type, "valid_until_ms": s.valid_until_ms,
                        "status": _signal_status(ups, s.entry_type), "updates": [u.to_dict() for u in ups]})
    out.sort(key=lambda d: d["event_time_ms"], reverse=True)
    return out[: max(1, min(limit, 1000))]


def signal_detail(root: Path, strategy_ids: list[str], signal_id: str) -> dict[str, Any] | None:
    for d in list_signals(root, strategy_ids, limit=1000):
        if d["signal_id"] == signal_id:
            return d
    return None


def known_strategy_ids(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


def read_json(path: Path) -> Any | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def research_runs(data_dir: Path, limit: int = 200) -> list[dict[str, Any]]:
    """Backtest / paper / WFO artifacts found on disk (manifest fields only; the numbers stay in the artifacts)."""
    out: list[dict[str, Any]] = []
    for kind, folder in (("backtest", "backtests"), ("paper", "paper")):
        root = data_dir / folder
        if not root.exists():
            continue
        for d in root.iterdir():
            run = read_json(d / "run.json") if d.is_dir() else None
            if run is None:
                continue
            m = run.get("metrics") or {}
            out.append({
                "kind": kind, "run_id": run.get("run_id"), "created_at": run.get("created_at"), "period": run.get("period"),
                "provider": run.get("provider"), "touched_test_set": run.get("touched_test_set"), "stress": run.get("stress"),
                "result_hash": run.get("result_hash"), "git_commit": run.get("git_commit"), "git_dirty": run.get("git_dirty"),
                "total_return": m.get("total_return"), "max_drawdown": m.get("max_drawdown"), "n_trades": m.get("n_trades"),
                "win_rate": m.get("win_rate"), "sharpe": m.get("sharpe"),
            })
    wfo = data_dir / "wfo"
    if wfo.exists():
        for d in wfo.iterdir():
            report = read_json(d / "report.json") if d.is_dir() else None
            if report is not None:
                out.append({"kind": "wfo", "run_id": d.name, "created_at": None, "period": None, "provider": None,
                            "touched_test_set": report.get("touched_test_set"), "stress": None, "result_hash": report.get("result_hash"),
                            "git_commit": None, "git_dirty": None, "total_return": None, "max_drawdown": None, "n_trades": None,
                            "win_rate": None, "sharpe": None})
    out.sort(key=lambda r: str(r["created_at"] or r["run_id"]), reverse=True)
    return out[:limit]


def outbox_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {status: int(n) for status, n in con.execute("SELECT status, count(*) FROM telegram_outbox GROUP BY status").fetchall()}
