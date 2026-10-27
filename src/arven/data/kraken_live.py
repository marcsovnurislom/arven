"""Live 1m minutes for spot forex (EUR/USD, GBP/USD) from Kraken's public OHLC endpoint (added 2026-10-27).

Why Kraken: Binance has no EUR/USD or GBP/USD contract, Dukascopy publishes a day's candles only after the day ends, and
Kraken's fiat pairs trade every minute (checked 2026-10-26: 721 of 721 minutes with trades for both; USD/JPY had
trades in 10 of 721, so it is not offered). The history before the live start is Dukascopy (``arven duka``); Kraken
minutes are appended to the **same symbol**, so features and strategies see one continuous series - the two sources
quote the same interbank price within a fraction of a pip, and the seam is documented, not hidden.

Rules: only closed minutes (open + 1m <= now); only minutes the session calendar marks open (no weekend prints);
only minutes after the last stored one (never overwrite history). Kraken serves the latest 720 minutes, so an outage
longer than 12 hours leaves a gap; ``arven --instrument EURUSD duka download/ingest`` fills it from Dukascopy.
Volume is Kraken's traded base volume (a liquidity proxy, as Dukascopy's tick volume is); trade flow columns are 0.
Public endpoint only - no keys, nothing that could place an order (CLAUDE.md rule 12).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import duckdb

from arven.core.config import AppConfig
from arven.core.timeframes import Timeframe
from arven.data.download import Downloader, RetryPolicy
from arven.data.rest_ingestion import RestTailSummary, bulk_insert_or_replace
from arven.data.storage.db import now_ms

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_PAIRS = {"EURUSD": "EURUSD", "GBPUSD": "GBPUSD"}  # ARVEN symbol -> Kraken pair
MIN_MS = Timeframe.M1.ms

_COLS = ["symbol", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume", "quote_volume",
         "trade_count", "taker_buy_volume", "taker_buy_quote_volume", "source_key", "ingested_at_ms"]
_TYPES = {"symbol": "VARCHAR", "open_time_ms": "BIGINT", "close_time_ms": "BIGINT", "open": "DOUBLE", "high": "DOUBLE",
          "low": "DOUBLE", "close": "DOUBLE", "volume": "DOUBLE", "quote_volume": "DOUBLE", "trade_count": "BIGINT",
          "taker_buy_volume": "DOUBLE", "taker_buy_quote_volume": "DOUBLE", "source_key": "VARCHAR", "ingested_at_ms": "BIGINT"}


def parse_ohlc(payload: dict[str, Any]) -> list[tuple[int, float, float, float, float, float, int]]:
    """Kraken's ``{"error": [], "result": {<pair>: [[time_s, o, h, l, c, vwap, volume, count], ...], "last": ...}}``
    -> ``(open_ms, open, high, low, close, volume, count)`` rows, ascending. Raises on an API error."""
    if payload.get("error"):
        raise ValueError(f"kraken: {payload['error']}")
    result = payload.get("result") or {}
    keys = [k for k in result if k != "last"]
    if len(keys) != 1:
        raise ValueError(f"kraken: expected one pair in the result, got {keys}")
    out = []
    for r in result[keys[0]]:
        t = int(r[0]) * 1000
        if t % MIN_MS:
            raise ValueError(f"kraken: bar time {t} not on a minute")
        out.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6]), int(r[7])))
    return sorted(out)


def select_new(rows: Sequence[tuple], last_stored_ms: int | None, now_ms_: int, is_open) -> list[tuple]:
    """The closed, in-session minutes after ``last_stored_ms`` (``is_open(open_ms) -> bool``)."""
    return [r for r in rows if r[0] + MIN_MS <= now_ms_ and (last_stored_ms is None or r[0] > last_stored_ms) and bool(is_open(r[0]))]


def fetch_new(app: AppConfig, last_ms: int | None, now_ms_: int, downloader: Downloader, summary: RestTailSummary) -> list[tuple]:
    """Kraken's closed, in-session minutes after ``last_ms`` (network only, no database); errors go to ``summary``."""
    pair = KRAKEN_PAIRS.get(app.market.symbol)
    if pair is None:
        summary.errors.append(f"kraken: no live pair for {app.market.symbol}")
        return []
    try:
        rows = parse_ohlc(json.loads(downloader.fetch_bytes(f"{KRAKEN_OHLC_URL}?pair={pair}&interval=1")))
    except Exception as exc:  # noqa: BLE001 - recorded, the tick then sees stale data and stays NO_TRADE
        summary.errors.append(f"kraken {pair}: {exc}")
        return []
    summary.pages += 1
    summary.klines_fetched += len(rows)
    return select_new(rows, last_ms, now_ms_, app.session_calendar().is_open)


def write_new(con: duckdb.DuckDBPyConnection, symbol: str, new: list[tuple]) -> int:
    """Store rows from :func:`fetch_new` (never overwriting: they all lie after the last stored minute)."""
    if not new:
        return 0
    key = f"kraken/{symbol}/{new[0][0]}"
    ingested = now_ms()
    data = [(symbol, t, t + MIN_MS, o, h, lo, c, v, v * c, n, 0.0, 0.0, key, ingested) for t, o, h, lo, c, v, n in new]
    bulk_insert_or_replace(con, "ohlcv_1m", _COLS, _TYPES, data)
    return len(data)


def kraken_tail(app: AppConfig, con: duckdb.DuckDBPyConnection, now_ms_: int, downloader: Downloader | None = None) -> RestTailSummary:
    """Append Kraken's new closed minutes for ``app.market.symbol`` to ``ohlcv_1m`` (see the module docstring)."""
    summary = RestTailSummary()
    symbol = app.market.symbol
    if symbol not in KRAKEN_PAIRS:
        summary.errors.append(f"kraken: no live pair for {symbol}")
        return summary
    row = con.execute("SELECT max(open_time_ms) FROM ohlcv_1m WHERE symbol = ?", [symbol]).fetchone()
    last = int(row[0]) if row and row[0] is not None else None
    new = fetch_new(app, last, now_ms_, downloader or Downloader(RetryPolicy.from_config(app.download)), summary)
    summary.klines_written = write_new(con, symbol, new)
    return summary


__all__ = ["KRAKEN_PAIRS", "fetch_new", "kraken_tail", "parse_ohlc", "select_new", "write_new"]
