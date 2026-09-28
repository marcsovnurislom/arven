"""Columnar point-in-time market-data containers (numpy).

These are the typed hand-over objects between the data layer (which reads them from storage) and the
feature layer (which consumes them). They carry no I/O and no business logic beyond validation and the
point-in-time operations every consumer needs:

- ``available_until(t_ms)``: the records that were known at ``t_ms`` (``available_at <= t_ms``);
- ``BarSeries.regularized()``: put bars on a gap-free grid, marking missing/incomplete bars as NaN.

All times are UTC epoch milliseconds (int64). Bars cover ``[open_time, open_time + tf.ms)`` and become
usable at ``open_time + tf.ms + delay_ms``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from arven.core.timeframes import Timeframe

_BAR_VALUE_FIELDS = ("open", "high", "low", "close", "volume", "trade_count", "taker_buy_volume")


def _as_i64(a: object) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.int64)


def _as_f64(a: object) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.float64)


@dataclass(frozen=True, eq=False)
class BarSeries:
    timeframe: Timeframe
    delay_ms: int
    open_time_ms: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    trade_count: np.ndarray
    taker_buy_volume: np.ndarray
    complete: np.ndarray  # False = bar missing or built from incomplete 1m data (values are NaN)

    def __post_init__(self) -> None:
        if self.delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        object.__setattr__(self, "open_time_ms", _as_i64(self.open_time_ms))
        for name in _BAR_VALUE_FIELDS:
            object.__setattr__(self, name, _as_f64(getattr(self, name)))
        object.__setattr__(self, "complete", np.ascontiguousarray(self.complete, dtype=bool))
        n = len(self.open_time_ms)
        for name in (*_BAR_VALUE_FIELDS, "complete"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"column {name} has length {len(getattr(self, name))}, expected {n}")
        if n:
            if np.any(np.diff(self.open_time_ms) <= 0):
                raise ValueError("open_time_ms must be strictly increasing")
            if np.any(self.open_time_ms % self.timeframe.ms != 0):
                raise ValueError(f"open_time_ms is not aligned to {self.timeframe}")

    def __len__(self) -> int:
        return len(self.open_time_ms)

    @property
    def close_time_ms(self) -> np.ndarray:
        return self.open_time_ms + self.timeframe.ms

    @property
    def available_at_ms(self) -> np.ndarray:
        return self.open_time_ms + (self.timeframe.ms + self.delay_ms)

    def _take(self, sl: slice) -> BarSeries:
        return BarSeries(
            self.timeframe,
            self.delay_ms,
            self.open_time_ms[sl],
            *(getattr(self, name)[sl] for name in _BAR_VALUE_FIELDS),
            self.complete[sl],
        )

    def available_until(self, t_ms: int) -> BarSeries:
        """Bars known at ``t_ms``: those with ``available_at <= t_ms``."""
        n = int(np.searchsorted(self.available_at_ms, t_ms, side="right"))
        return self._take(slice(0, n))

    def regularized(self) -> BarSeries:
        """Gap-free grid from the first to the last stored bar.

        Missing bars, and bars flagged incomplete, become NaN rows with ``complete=False``. Nothing is
        interpolated or carried forward, so ``shift(k)`` on the result always means "k bars earlier".
        """
        if len(self) == 0:
            return self
        step = self.timeframe.ms
        first, last = int(self.open_time_ms[0]), int(self.open_time_ms[-1])
        grid = np.arange(first, last + step, step, dtype=np.int64)
        pos = (self.open_time_ms - first) // step
        keep = self.complete
        cols = {}
        for name in _BAR_VALUE_FIELDS:
            col = np.full(len(grid), np.nan)
            col[pos[keep]] = getattr(self, name)[keep]
            cols[name] = col
        complete = np.zeros(len(grid), dtype=bool)
        complete[pos[keep]] = True
        return BarSeries(self.timeframe, self.delay_ms, grid, complete=complete, **cols)


@dataclass(frozen=True, eq=False)
class FundingSeries:
    funding_time_ms: np.ndarray  # normalised to the funding grid
    available_at_ms: np.ndarray
    funding_rate: np.ndarray
    interval_hours: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "funding_time_ms", _as_i64(self.funding_time_ms))
        object.__setattr__(self, "available_at_ms", _as_i64(self.available_at_ms))
        object.__setattr__(self, "funding_rate", _as_f64(self.funding_rate))
        object.__setattr__(self, "interval_hours", _as_i64(self.interval_hours))
        n = len(self.funding_time_ms)
        if not (len(self.available_at_ms) == len(self.funding_rate) == len(self.interval_hours) == n):
            raise ValueError("funding columns must have equal length")
        if n and (np.any(np.diff(self.funding_time_ms) <= 0) or np.any(np.diff(self.available_at_ms) < 0)):
            raise ValueError("funding records must be strictly increasing in time and non-decreasing in available_at")

    def __len__(self) -> int:
        return len(self.funding_time_ms)

    def available_until(self, t_ms: int) -> FundingSeries:
        n = int(np.searchsorted(self.available_at_ms, t_ms, side="right"))
        return FundingSeries(
            self.funding_time_ms[:n], self.available_at_ms[:n], self.funding_rate[:n], self.interval_hours[:n]
        )


@dataclass(frozen=True, eq=False)
class OpenInterestSeries:
    ts_ms: np.ndarray  # snapshot time
    available_at_ms: np.ndarray  # ts + configured publication delay
    sum_open_interest: np.ndarray
    top_trader_ls_ratio: np.ndarray  # sum_toptrader_long_short_ratio
    taker_ls_vol_ratio: np.ndarray  # sum_taker_long_short_vol_ratio

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_ms", _as_i64(self.ts_ms))
        object.__setattr__(self, "available_at_ms", _as_i64(self.available_at_ms))
        for name in ("sum_open_interest", "top_trader_ls_ratio", "taker_ls_vol_ratio"):
            object.__setattr__(self, name, _as_f64(getattr(self, name)))
        n = len(self.ts_ms)
        for name in ("available_at_ms", "sum_open_interest", "top_trader_ls_ratio", "taker_ls_vol_ratio"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"column {name} has wrong length")
        if n and (np.any(np.diff(self.ts_ms) <= 0) or np.any(np.diff(self.available_at_ms) < 0)):
            raise ValueError("open-interest records must be strictly increasing in time")

    def __len__(self) -> int:
        return len(self.ts_ms)

    def available_until(self, t_ms: int) -> OpenInterestSeries:
        n = int(np.searchsorted(self.available_at_ms, t_ms, side="right"))
        return OpenInterestSeries(
            self.ts_ms[:n],
            self.available_at_ms[:n],
            self.sum_open_interest[:n],
            self.top_trader_ls_ratio[:n],
            self.taker_ls_vol_ratio[:n],
        )


# Timeframes a complete market-data snapshot must contain (the v1 features read all of them).
REQUIRED_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4)


@dataclass(frozen=True, eq=False)
class MarketInputs:
    bars: Mapping[Timeframe, BarSeries]
    funding: FundingSeries
    open_interest: OpenInterestSeries

    def __post_init__(self) -> None:
        missing = [tf.value for tf in REQUIRED_TIMEFRAMES if tf not in self.bars]
        if missing:
            raise ValueError(f"missing bar series for timeframes: {missing}")
        for tf, series in self.bars.items():
            if series.timeframe != tf:
                raise ValueError(f"bar series stored under {tf} has timeframe {series.timeframe}")

    def available_until(self, t_ms: int) -> MarketInputs:
        """Everything that was known at ``t_ms`` and nothing else (used by live loops and leakage tests)."""
        return MarketInputs(
            bars={tf: s.available_until(t_ms) for tf, s in self.bars.items()},
            funding=self.funding.available_until(t_ms),
            open_interest=self.open_interest.available_until(t_ms),
        )

    def fingerprint(self) -> str:
        """SHA-256 over every input array (NaN canonicalised): identifies the exact data a build used."""
        h = hashlib.sha256()

        def feed(name: str, a: np.ndarray) -> None:
            a = np.ascontiguousarray(a)
            if a.dtype.kind == "f":
                a = np.where(np.isnan(a), np.nan, a)
            h.update(name.encode())
            h.update(str(a.shape).encode())
            h.update(a.tobytes())

        for tf in sorted(self.bars, key=lambda x: x.ms):
            s = self.bars[tf]
            h.update(f"bars:{tf.value}:{s.delay_ms}".encode())
            feed("open_time_ms", s.open_time_ms)
            for name in ("open", "high", "low", "close", "volume", "trade_count", "taker_buy_volume"):
                feed(name, getattr(s, name))
            feed("complete", s.complete)
        f = self.funding
        for name in ("funding_time_ms", "available_at_ms", "funding_rate", "interval_hours"):
            feed("funding." + name, getattr(f, name))
        o = self.open_interest
        for name in ("ts_ms", "available_at_ms", "sum_open_interest", "top_trader_ls_ratio", "taker_ls_vol_ratio"):
            feed("oi." + name, getattr(o, name))
        return h.hexdigest()
