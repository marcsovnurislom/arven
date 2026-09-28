"""Deterministic 1m -> higher-timeframe resampling (5m, 15m, 1h, 4h).

Each 1m bar belongs to bucket ``open_time - open_time % tf_ms`` (UTC-epoch aligned; matches Binance).
open = first 1m open, close = last 1m close, high = max, low = min, volumes and trade counts summed.
Sums are computed in DECIMAL(38, 8) so the result is exact and independent of summation order
(Binance quantities have at most 8 decimals), then stored as DOUBLE.

A bucket with fewer 1m bars than it should have is still stored, with ``is_complete = false`` and its
``bar_count``; consumers must not treat incomplete bars as normal bars. Buckets with no 1m data at all
are absent (a gap).
"""

from __future__ import annotations

from datetime import datetime

import duckdb

from arven.core.time import to_ms
from arven.core.timeframes import Timeframe, ceil_to_bar, floor_to_bar
from arven.data.storage.db import now_ms

DERIVED_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4)


def _exact_sum(column: str) -> str:
    return f"CAST(sum(CAST({column} AS DECIMAL(38, 8))) AS DOUBLE)"


def resample(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    start: datetime,
    end: datetime,
    timeframes: tuple[Timeframe, ...] = DERIVED_TIMEFRAMES,
) -> dict[Timeframe, int]:
    """(Re)build derived bars for every bucket overlapping ``[start, end)``. Returns rows written per timeframe."""
    written: dict[Timeframe, int] = {}
    built_at = now_ms()
    for tf in timeframes:
        if tf is Timeframe.M1:
            raise ValueError("1m is the base timeframe and is not resampled")
        lo, hi = to_ms(floor_to_bar(start, tf)), to_ms(ceil_to_bar(end, tf))
        minutes = tf.ms // Timeframe.M1.ms
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                "DELETE FROM ohlcv WHERE symbol = ? AND timeframe = ? AND open_time_ms >= ? AND open_time_ms < ?",
                [symbol, tf.value, lo, hi],
            )
            con.execute(
                f"""
                INSERT INTO ohlcv
                SELECT symbol, ?, bucket, bucket + {tf.ms},
                       arg_min(open, open_time_ms), max(high), min(low), arg_max(close, open_time_ms),
                       {_exact_sum('volume')}, {_exact_sum('quote_volume')}, sum(trade_count),
                       {_exact_sum('taker_buy_volume')}, {_exact_sum('taker_buy_quote_volume')},
                       count(*), count(*) = {minutes}, ?
                FROM (
                    SELECT *, open_time_ms - open_time_ms % {tf.ms} AS bucket
                    FROM ohlcv_1m
                    WHERE symbol = ? AND open_time_ms >= ? AND open_time_ms < ?
                )
                GROUP BY symbol, bucket
                """,
                [tf.value, built_at, symbol, lo, hi],
            )
            count = con.execute(
                "SELECT count(*) FROM ohlcv WHERE symbol = ? AND timeframe = ? AND open_time_ms >= ? AND open_time_ms < ?",
                [symbol, tf.value, lo, hi],
            ).fetchone()[0]
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        written[tf] = int(count)
    return written
