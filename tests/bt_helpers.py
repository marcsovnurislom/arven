"""Helpers for backtest tests: tiny hand-made markets, scripted providers, zero-cost configs."""

from __future__ import annotations

from typing import Any

import numpy as np

from arven.backtest.engine import Backtester, BacktestResult
from arven.backtest.marketdata import MINUTE_MS, MarketData, align_funding
from arven.backtest.provider import DecisionContext, FeatureData, PrepareInfo
from arven.core.backtest_config import BacktestConfig, load_backtest_config
from arven.core.config import AppConfig, CostsConfig, load_config
from arven.core.signal import Signal
from arven.core.splitguard import AllowedWindow, BacktestPeriod, SplitGuard
from arven.core.types import Action

HOUR = 3_600_000
T0 = 1_609_718_400_000  # 2021-01-04 00:00 UTC, inside the development period, a funding time
FUNDING_INTERVAL = 8 * HOUR

_APP = load_config()


def app_config(**costs_updates: Any) -> AppConfig:
    """Repo config with optional cost overrides given as nested dicts, e.g. ``fees={'taker_fee_bps': 0.0}``."""
    if not costs_updates:
        return _APP
    d = _APP.costs.model_dump()
    for k, v in costs_updates.items():
        d[k] = {**d[k], **v}
    return _APP.model_copy(update={"costs": CostsConfig.model_validate(d)})


def zero_cost_app() -> AppConfig:
    return app_config(fees={"taker_fee_bps": 0.0, "maker_fee_bps": 0.0}, slippage={"fixed_bps": 0.0, "volatility_multiplier": 0.0})


def bt_config(**updates: Any) -> BacktestConfig:
    base = load_backtest_config()
    return BacktestConfig.model_validate({**base.model_dump(), **updates})


def window(hours: int, start_ms: int = T0) -> AllowedWindow:
    return SplitGuard(_APP.splits).resolve(BacktestPeriod.DEVELOPMENT, start_ms, start_ms + hours * HOUR)


def flat_bar(price: float) -> tuple[float, float, float, float]:
    return (price, price, price, price)


def make_market(
    hours: int,
    bars: dict[int, tuple[float, float, float, float]] | None = None,
    *,
    base_price: float = 30_000.0,
    funding_rates: dict[int, float] | None = None,
    drop_minutes: set[int] | None = None,
    start_ms: int = T0,
    drop_funding: set[int] | None = None,
) -> MarketData:
    """``bars`` maps minute index -> (o, h, l, c); every other minute is flat at the previous close."""
    n = hours * 60
    o = np.empty(n)
    h = np.empty(n)
    l = np.empty(n)  # noqa: E741
    c = np.empty(n)
    last = base_price
    for i in range(n):
        bo, bh, bl, bc = (bars or {}).get(i, flat_bar(last))
        o[i], h[i], l[i], c[i] = bo, bh, bl, bc
        last = bc
    times = start_ms + np.arange(n, dtype=np.int64) * MINUTE_MS
    keep = np.ones(n, dtype=bool)
    for m in drop_minutes or ():
        keep[m] = False
    end_ms = start_ms + hours * HOUR
    if funding_rates is None:  # default: a zero rate at every funding time (pass a dict to control / omit rates)
        rates = {int(x): 0.0 for x in np.arange(start_ms, end_ms + FUNDING_INTERVAL, FUNDING_INTERVAL)}
    else:
        rates = funding_rates
    row_t = np.array(sorted(t for t in rates if t not in (drop_funding or set())), dtype=np.int64)
    row_r = np.array([rates[int(t)] for t in row_t])
    ft, fr = align_funding(row_t, row_r, start_ms, end_ms, FUNDING_INTERVAL)
    return MarketData(times[keep], o[keep], h[keep], l[keep], c[keep], start_ms, end_ms, ft, fr, FUNDING_INTERVAL)


def features_for(win: AllowedWindow, ready: bool = True) -> FeatureData:
    n = win.n_hours
    t = win.start_ms + np.arange(n, dtype=np.int64) * HOUR
    return FeatureData(t, ("feat_ready",), np.full((n, 1), 1.0 if ready else 0.0), win.start_ms)


class Scripted:
    """Provider that emits pre-defined signals at given decision times."""

    def __init__(self, signals: dict[int, Signal]) -> None:
        self._signals = signals
        self.seen: list[int] = []

    def describe(self) -> dict[str, Any]:
        return {"name": "scripted"}

    def prepare(self, info: PrepareInfo) -> None:
        return None

    def decide(self, ctx: DecisionContext) -> Signal | None:
        self.seen.append(ctx.now_ms)
        return self._signals.get(ctx.now_ms)


def long_signal(t: int, fraction: float = 0.5, **kw: Any) -> Signal:
    return Signal(t, Action.LONG, notional_fraction=fraction, **kw)


def short_signal(t: int, fraction: float = 0.5, **kw: Any) -> Signal:
    return Signal(t, Action.SHORT, notional_fraction=fraction, **kw)


def run(
    market: MarketData,
    signals: dict[int, Signal],
    *,
    app: AppConfig | None = None,
    cfg: BacktestConfig | None = None,
    stress: bool = False,
    hours: int | None = None,
) -> BacktestResult:
    hours = hours if hours is not None else (market.window_end_ms - market.window_start_ms) // HOUR
    win = window(hours, market.window_start_ms)
    bt = Backtester(app or zero_cost_app(), cfg or bt_config(), win, market, features_for(win), stress=stress)
    return bt.run(Scripted(signals))


def truncate_market(md: MarketData, keep_hours: int) -> MarketData:
    """The same market cut after ``keep_hours`` hours (window shortened accordingly)."""
    end = md.window_start_ms + keep_hours * HOUR
    k = int(np.searchsorted(md.time_ms, end))
    fmask = md.funding_time_ms < end
    return MarketData(
        md.time_ms[:k], md.open[:k], md.high[:k], md.low[:k], md.close[:k], md.window_start_ms, end,
        md.funding_time_ms[fmask], md.funding_rate[fmask], md.funding_interval_ms,
    )


def garbage_after(md: MarketData, from_hour: int, seed: int = 99) -> MarketData:
    """Same times, but every bar / funding rate from ``from_hour`` on replaced by random valid values."""
    rng = np.random.default_rng(seed)
    cut = md.window_start_ms + from_hour * HOUR
    k = int(np.searchsorted(md.time_ms, cut))
    n = len(md.time_ms) - k
    o, h, l, c = md.open.copy(), md.high.copy(), md.low.copy(), md.close.copy()  # noqa: E741
    base = rng.uniform(5_000, 90_000, n)
    op = base * (1 + rng.normal(0, 0.01, n))
    cl = base * (1 + rng.normal(0, 0.01, n))
    o[k:], c[k:] = op, cl
    h[k:] = np.maximum(op, cl) * (1 + np.abs(rng.normal(0, 0.005, n)))
    l[k:] = np.minimum(op, cl) * (1 - np.abs(rng.normal(0, 0.005, n)))
    fr = md.funding_rate.copy()
    fmask = md.funding_time_ms >= cut
    fr[fmask] = rng.normal(0, 0.002, int(fmask.sum()))
    return MarketData(md.time_ms, o, h, l, c, md.window_start_ms, md.window_end_ms, md.funding_time_ms, fr, md.funding_interval_ms)


def bulk_insert_1m(con, rows: list[tuple]) -> None:
    """Fast bulk insert of ``ohlcv_1m`` rows via ``COPY FROM`` a temp CSV (row-by-row parameter binding into a
    PRIMARY KEY-indexed table is pathologically slow in this DuckDB version - the same reason Stage 2's real
    ingestion loads through ``COPY`` / ``read_csv`` rather than per-row inserts; see docs/current_state.md)."""
    cols = ["symbol", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume",
            "quote_volume", "trade_count", "taker_buy_volume", "taker_buy_quote_volume", "source_key", "ingested_at_ms"]
    _copy_insert(con, "ohlcv_1m", cols, rows)


def bulk_insert_funding(con, rows: list[tuple]) -> None:
    """Fast bulk insert of ``funding_rates`` rows (see :func:`bulk_insert_1m`)."""
    cols = ["symbol", "funding_time_ms", "raw_funding_time_ms", "funding_rate", "funding_interval_hours",
            "available_at_ms", "source_key", "ingested_at_ms"]
    _copy_insert(con, "funding_rates", cols, rows)


def _copy_insert(con, table: str, cols: list[str], rows: list[tuple]) -> None:
    import csv
    import os
    import tempfile

    if not rows:
        return
    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows)
        con.execute(f"COPY {table} FROM '{path.replace(chr(92), '/')}' (HEADER, DELIMITER ',')")
    finally:
        os.unlink(path)
