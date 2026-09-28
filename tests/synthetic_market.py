"""Deterministic synthetic market data for feature tests (no network, no database)."""

from __future__ import annotations

import numpy as np

from arven.core.series import BarSeries, FundingSeries, MarketInputs, OpenInterestSeries
from arven.core.timeframes import Timeframe

HOUR = 3_600_000
DAY = 24 * HOUR
# 2021-01-04 00:00 UTC, a Monday, aligned to every timeframe.
START_MS = 1_609_718_400_000


def make_5m(n: int, seed: int = 1, start_ms: int = START_MS) -> dict[str, np.ndarray]:
    """Random-walk 5m bars with a consistent OHLC structure and positive volumes."""
    rng = np.random.default_rng(seed)
    close = 30_000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0015, n)))
    open_ = np.concatenate(([30_000.0], close[:-1]))
    up = np.abs(rng.normal(0.0, 0.0006, n))
    down = np.abs(rng.normal(0.0, 0.0006, n))
    high = np.maximum(open_, close) * (1 + up)
    low = np.minimum(open_, close) * (1 - down)
    volume = rng.lognormal(3.0, 0.5, n)
    return {
        "open_time_ms": start_ms + np.arange(n, dtype=np.int64) * Timeframe.M5.ms,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "trade_count": np.round(volume * 40.0) + 1.0,
        "taker_buy_volume": volume * rng.uniform(0.3, 0.7, n),
    }


def aggregate(five: dict[str, np.ndarray], tf: Timeframe, delay_ms: int = 0) -> BarSeries:
    """Aggregate 5m bars into ``tf`` bars (exactly like the 1m -> higher-TF resampler would)."""
    k = tf.ms // Timeframe.M5.ms
    n = len(five["close"]) // k * k
    if n == 0:
        raise ValueError("not enough 5m bars")
    r = {name: col[:n].reshape(-1, k) for name, col in five.items()}
    return BarSeries(
        timeframe=tf,
        delay_ms=delay_ms,
        open_time_ms=r["open_time_ms"][:, 0],
        open=r["open"][:, 0],
        high=r["high"].max(axis=1),
        low=r["low"].min(axis=1),
        close=r["close"][:, -1],
        volume=r["volume"].sum(axis=1),
        trade_count=r["trade_count"].sum(axis=1),
        taker_buy_volume=r["taker_buy_volume"].sum(axis=1),
        complete=np.ones(n // k, dtype=bool),
    )


def make_funding(n_days: int, seed: int = 2, start_ms: int = START_MS, jitter_ms: int = 0) -> FundingSeries:
    rng = np.random.default_rng(seed)
    n = n_days * 3
    times = start_ms + np.arange(n, dtype=np.int64) * 8 * HOUR
    return FundingSeries(
        funding_time_ms=times,
        available_at_ms=times + jitter_ms,
        funding_rate=rng.normal(1e-4, 5e-5, n),
        interval_hours=np.full(n, 8, dtype=np.int64),
    )


def make_oi(n_days: int, seed: int = 3, start_ms: int = START_MS, delay_ms: int = 300_000) -> OpenInterestSeries:
    rng = np.random.default_rng(seed)
    n = n_days * 288
    ts = start_ms + np.arange(n, dtype=np.int64) * 300_000
    oi = 80_000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.002, n)))
    return OpenInterestSeries(
        ts_ms=ts,
        available_at_ms=ts + delay_ms,
        sum_open_interest=oi,
        top_trader_ls_ratio=rng.uniform(0.6, 2.0, n),
        taker_ls_vol_ratio=rng.uniform(0.6, 1.6, n),
    )


def make_market(n_days: int = 240, seed: int = 1, delay_ms: int = 0) -> MarketInputs:
    five = make_5m(n_days * 288, seed)
    return MarketInputs(
        bars={
            Timeframe.M5: aggregate(five, Timeframe.M5, delay_ms),
            Timeframe.M15: aggregate(five, Timeframe.M15, delay_ms),
            Timeframe.H1: aggregate(five, Timeframe.H1, delay_ms),
            Timeframe.H4: aggregate(five, Timeframe.H4, delay_ms),
        },
        funding=make_funding(n_days, seed + 1),
        open_interest=make_oi(n_days, seed + 2),
    )


def hourly_grid(inputs: MarketInputs, first_hour: int = 0) -> np.ndarray:
    """Every 1h close inside the synthetic data, starting ``first_hour`` hours after the first bar."""
    h1 = inputs.bars[Timeframe.H1]
    return h1.close_time_ms[first_hour:]
