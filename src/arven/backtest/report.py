"""Canonical serialisation and hashing of a backtest result (pure; file writing lives in ``arven.runs``).

The ledgers are rendered as CSV text with fixed column order and floats rounded to 10 decimals, so the same
result always yields the same bytes. ``result_hash`` is the SHA-256 over the per-table hashes; it contains no
timestamps, run ids or machine-specific values.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import fields
from enum import Enum
from typing import Any

from arven.backtest.engine import BacktestResult

TABLE_ORDER = ("meta", "orders", "fills", "funding", "trades", "equity")


def _fmt(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, Enum):
        return str(x.value)
    if isinstance(x, bool):
        return "1" if x else "0"
    if isinstance(x, float):
        if math.isnan(x):
            return "nan"
        return format(round(x, 10) + 0.0, ".10f")
    return str(x)


fmt_value = _fmt


def records_csv(records: tuple[Any, ...] | list[Any], cls: type) -> str:
    names = [f.name for f in fields(cls)]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(names)
    for r in records:
        w.writerow([_fmt(getattr(r, n)) for n in names])
    return buf.getvalue()


def result_tables(result: BacktestResult) -> dict[str, str]:
    from arven.backtest.types import EquityPoint, Fill, FundingEvent, OrderEvent, Trade

    meta = {
        "period": result.period,
        "window_start_ms": result.window_start_ms,
        "window_end_ms": result.window_end_ms,
        "initial_equity": _fmt(result.initial_equity),
        "final_wallet": _fmt(result.final_wallet),
        "n_decisions": result.n_decisions,
        "signal_counts": dict(sorted(result.signal_counts.items())),
        "stress": result.stress,
        "low_points": [[t, _fmt(v)] for t, v in result.low_points],
    }
    return {
        "meta": json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n",
        "orders": records_csv(result.orders, OrderEvent),
        "fills": records_csv(result.fills, Fill),
        "funding": records_csv(result.funding, FundingEvent),
        "trades": records_csv(result.trades, Trade),
        "equity": records_csv(result.equity, EquityPoint),
    }


def table_hashes(tables: dict[str, str]) -> dict[str, str]:
    return {name: hashlib.sha256(tables[name].encode("utf-8")).hexdigest() for name in TABLE_ORDER}


def combine_hashes(hashes: dict[str, str]) -> str:
    h = hashlib.sha256()
    for name in TABLE_ORDER:
        h.update(f"{name}:{hashes[name]}\n".encode())
    return h.hexdigest()


def result_hash(result: BacktestResult) -> str:
    return combine_hashes(table_hashes(result_tables(result)))
