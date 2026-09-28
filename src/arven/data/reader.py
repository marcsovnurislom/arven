"""Read stored market data into point-in-time columnar series (:mod:`arven.core.series`).

Read-only: this module never writes to the database. Availability delays from the configuration are
applied here (bars) or already stored (funding, open interest), so consumers see one ``available_at``
convention.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np

from arven.core.config import AppConfig
from arven.core.series import REQUIRED_TIMEFRAMES, BarSeries, FundingSeries, MarketInputs, OpenInterestSeries
from arven.core.time import to_ms
from arven.core.timeframes import Timeframe


def open_readonly(database_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open the ARVEN database read-only (no schema DDL, safe next to a running writer)."""
    return duckdb.connect(str(database_path), read_only=True)


def _f64(a: object) -> np.ndarray:
    return np.ma.filled(np.ma.asarray(a).astype(np.float64), np.nan)


def _i64(a: object) -> np.ndarray:
    return np.asarray(a, dtype=np.int64)


def load_bars(
    con: duckdb.DuckDBPyConnection, symbol: str, tf: Timeframe, start_ms: int, end_ms: int, delay_ms: int
) -> BarSeries:
    """Derived bars whose interval lies inside ``[start_ms, end_ms]``, oldest first."""
    d = con.execute(
        "SELECT open_time_ms, open, high, low, close, volume, trade_count, taker_buy_volume, is_complete "
        "FROM ohlcv WHERE symbol = ? AND timeframe = ? AND open_time_ms >= ? AND close_time_ms <= ? "
        "ORDER BY open_time_ms",
        [symbol, tf.value, start_ms, end_ms],
    ).fetchnumpy()
    return BarSeries(
        timeframe=tf,
        delay_ms=delay_ms,
        open_time_ms=_i64(d["open_time_ms"]),
        open=_f64(d["open"]),
        high=_f64(d["high"]),
        low=_f64(d["low"]),
        close=_f64(d["close"]),
        volume=_f64(d["volume"]),
        trade_count=_f64(d["trade_count"]),
        taker_buy_volume=_f64(d["taker_buy_volume"]),
        complete=np.asarray(d["is_complete"], dtype=bool),
    )


def load_funding(con: duckdb.DuckDBPyConnection, symbol: str, start_ms: int, end_ms: int) -> FundingSeries:
    d = con.execute(
        "SELECT funding_time_ms, available_at_ms, funding_rate, funding_interval_hours FROM funding_rates "
        "WHERE symbol = ? AND funding_time_ms >= ? AND funding_time_ms < ? ORDER BY funding_time_ms",
        [symbol, start_ms, end_ms],
    ).fetchnumpy()
    return FundingSeries(
        _i64(d["funding_time_ms"]), _i64(d["available_at_ms"]), _f64(d["funding_rate"]), _i64(d["funding_interval_hours"])
    )


def load_open_interest(con: duckdb.DuckDBPyConnection, symbol: str, start_ms: int, end_ms: int) -> OpenInterestSeries:
    d = con.execute(
        "SELECT ts_ms, available_at_ms, sum_open_interest, sum_toptrader_long_short_ratio, "
        "sum_taker_long_short_vol_ratio FROM open_interest "
        "WHERE symbol = ? AND ts_ms >= ? AND ts_ms < ? ORDER BY ts_ms",
        [symbol, start_ms, end_ms],
    ).fetchnumpy()
    return OpenInterestSeries(
        _i64(d["ts_ms"]),
        _i64(d["available_at_ms"]),
        _f64(d["sum_open_interest"]),
        _f64(d["sum_toptrader_long_short_ratio"]),
        _f64(d["sum_taker_long_short_vol_ratio"]),
    )


def load_feature_inputs(
    con: duckdb.DuckDBPyConnection, cfg: AppConfig, start: datetime | None = None, end: datetime | None = None
) -> MarketInputs:
    """All inputs the feature builder needs over ``[start, end)`` (default: the configured history).

    Features are always computed from the first stored bar so that recursive indicators are seeded
    identically in every build; callers slice the *output* by decision time.
    """
    start_ms = to_ms(start or cfg.data.history_start)
    end_ms = to_ms(end or cfg.data.history_end)
    symbol = cfg.market.symbol
    delay_ms = cfg.data.bar_availability_delay_seconds * 1000
    return MarketInputs(
        bars={tf: load_bars(con, symbol, tf, start_ms, end_ms, delay_ms) for tf in REQUIRED_TIMEFRAMES},
        funding=load_funding(con, symbol, start_ms, end_ms),
        open_interest=load_open_interest(con, symbol, start_ms, end_ms),
    )
