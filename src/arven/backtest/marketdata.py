"""1m market data and funding schedule as validated numpy arrays."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from arven.backtest.errors import DataError
from arven.core.config import FundingConfig
from arven.core.sessions import SessionCalendar

MINUTE_MS = 60_000


@dataclass(frozen=True, eq=False)
class MarketData:
    """1m OHLC bars and the funding schedule of one window ``[window_start_ms, window_end_ms)``.

    Funding times are the epoch-aligned grid of ``funding_interval_ms`` inside the window; ``funding_rate`` is
    NaN where the stored data has no rate for a grid time (handled by ``costs.funding.missing_policy``).

    ``calendar`` (``None`` = around the clock) decides what a *data gap* is: a missing minute in which the market
    was open. A weekend or the daily halt of a session market is not a gap, so a position simply carries over it
    (a stop gapped through at the reopen fills at the reopen price, like any other gap-through).
    """

    time_ms: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    window_start_ms: int
    window_end_ms: int
    funding_time_ms: np.ndarray
    funding_rate: np.ndarray
    funding_interval_ms: int
    calendar: SessionCalendar | None = None
    gap_indices: np.ndarray = field(init=False, repr=False)  # j where bar j-1 is not the previous open minute
    funding_bar_index: np.ndarray = field(init=False, repr=False)  # bar index of each funding time, -1 if absent

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, np.ascontiguousarray(getattr(self, name), dtype=np.float64))
        object.__setattr__(self, "time_ms", np.ascontiguousarray(self.time_ms, dtype=np.int64))
        object.__setattr__(self, "funding_time_ms", np.ascontiguousarray(self.funding_time_ms, dtype=np.int64))
        object.__setattr__(self, "funding_rate", np.ascontiguousarray(self.funding_rate, dtype=np.float64))
        n = len(self.time_ms)
        if not (len(self.open) == len(self.high) == len(self.low) == len(self.close) == n):
            raise DataError("1m columns must have equal length")
        if len(self.funding_time_ms) != len(self.funding_rate):
            raise DataError("funding columns must have equal length")
        if n:
            t = self.time_ms
            if t[0] < self.window_start_ms or t[-1] >= self.window_end_ms:
                raise DataError("1m bars outside the window")
            if np.any(np.diff(t) <= 0):
                raise DataError("1m bar times must be strictly increasing")
            if np.any(t % MINUTE_MS != 0):
                raise DataError("1m bar times must be aligned to the minute")
            o, h, l, c = self.open, self.high, self.low, self.close  # noqa: E741
            if not (np.isfinite(o).all() and np.isfinite(h).all() and np.isfinite(l).all() and np.isfinite(c).all()):
                raise DataError("non-finite prices")
            if np.any(l <= 0) or np.any(h < l) or np.any(np.maximum(o, c) > h) or np.any(np.minimum(o, c) < l):
                raise DataError("invalid OHLC (need 0 < low <= open, close <= high)")
        gaps = np.flatnonzero(np.diff(self.time_ms) > MINUTE_MS) + 1 if n else np.array([], dtype=np.int64)
        if len(gaps) and self.calendar is not None and not self.calendar.always_open:
            # keep a jump only if at least one minute inside it was a trading minute
            real = [j for j in gaps if len(self.calendar.open_minutes(int(self.time_ms[j - 1]) + MINUTE_MS, int(self.time_ms[j])))]
            gaps = np.asarray(real, dtype=np.int64)
        object.__setattr__(self, "gap_indices", gaps)
        ft = self.funding_time_ms
        if len(ft) and (np.any(np.diff(ft) <= 0) or np.any(ft % self.funding_interval_ms != 0)):
            raise DataError("funding times must be increasing and on the funding grid")
        idx = np.searchsorted(self.time_ms, ft) if n else np.zeros(len(ft), dtype=np.int64)
        safe = np.minimum(idx, max(n - 1, 0))
        present = (idx < n) & (self.time_ms[safe] == ft) if n else np.zeros(len(ft), dtype=bool)
        object.__setattr__(self, "funding_bar_index", np.where(present, idx, -1).astype(np.int64))

    def __len__(self) -> int:
        return len(self.time_ms)

    def index_of(self, t_ms: int) -> int:
        """Index of the bar opening exactly at ``t_ms``, or -1 if there is none."""
        j = int(np.searchsorted(self.time_ms, t_ms))
        return j if j < len(self.time_ms) and int(self.time_ms[j]) == t_ms else -1

    def first_at_or_after(self, t_ms: int) -> int:
        return int(np.searchsorted(self.time_ms, t_ms))

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for name in ("time_ms", "open", "high", "low", "close", "funding_time_ms", "funding_rate"):
            a = np.ascontiguousarray(getattr(self, name))
            if a.dtype.kind == "f":
                a = np.where(np.isnan(a), np.nan, a)
            h.update(name.encode())
            h.update(a.tobytes())
        h.update(f"{self.window_start_ms}:{self.window_end_ms}:{self.funding_interval_ms}".encode())
        if self.calendar is not None and not self.calendar.always_open:  # around the clock: hash unchanged
            h.update(f"calendar:{self.calendar.kind}:{self.calendar.extra_closures}".encode())
        return h.hexdigest()


def funding_grid(start_ms: int, end_ms: int, interval_ms: int) -> np.ndarray:
    """Epoch-aligned funding times in ``[start_ms, end_ms)``."""
    first = -(-start_ms // interval_ms) * interval_ms
    return np.arange(first, end_ms, interval_ms, dtype=np.int64)


def align_funding(
    row_times_ms: np.ndarray, row_rates: np.ndarray, start_ms: int, end_ms: int, interval_ms: int
) -> tuple[np.ndarray, np.ndarray]:
    """Funding schedule on the expected grid: stored rates where present, NaN where a grid time has no row."""
    grid = funding_grid(start_ms, end_ms, interval_ms)
    rows_t = np.asarray(row_times_ms, dtype=np.int64)
    rows_r = np.asarray(row_rates, dtype=np.float64)
    rows_in = (rows_t >= start_ms) & (rows_t < end_ms)
    rows_t, rows_r = rows_t[rows_in], rows_r[rows_in]
    if len(rows_t) and not np.isin(rows_t, grid).all():
        raise DataError("stored funding times are not on the expected funding grid")
    rates = np.full(len(grid), np.nan)
    if len(rows_t):
        rates[np.searchsorted(grid, rows_t)] = rows_r
    return grid, rates


def funding_schedule(
    funding_cfg: FundingConfig, row_times_ms: np.ndarray, row_rates: np.ndarray, start_ms: int, end_ms: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """``(funding_time_ms, funding_rate, interval_ms)`` for a window: the stored rates on the funding grid
    (:func:`align_funding`), or no funding events at all when ``costs.funding.source`` is ``none`` (a CFD whose
    holding cost is not a perpetual-swap funding rate)."""
    interval_ms = funding_cfg.default_interval_hours * 3_600_000
    if funding_cfg.source == "none":
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64), interval_ms
    ft, fr = align_funding(row_times_ms, row_rates, start_ms, end_ms, interval_ms)
    return ft, fr, interval_ms
