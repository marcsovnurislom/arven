"""What a signal source sees at a decision time, and the protocol it implements.

A provider gets a :class:`DecisionContext`: the clock time, a :class:`FeatureView` that refuses to show
anything after that time, and a read-only :class:`PortfolioSnapshot`. It never sees raw market data.
The (later) strategy / decision / risk stack plugs in by implementing :class:`SignalProvider`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from arven.backtest.clock import HOUR_MS, Clock
from arven.backtest.errors import LookAheadError
from arven.core.signal import Signal


@dataclass(frozen=True, eq=False)
class FeatureData:
    """Feature rows of one window: a contiguous hourly grid of decision times and a (rows x columns) matrix."""

    t_ms: np.ndarray
    names: tuple[str, ...]
    values: np.ndarray
    first_ready_ms: int | None


class FeatureView:
    """Causal, read-only view of the Stage 3 feature table for one window, bound to the simulation clock."""

    def __init__(self, t_ms: np.ndarray, names: tuple[str, ...], values: np.ndarray, clock: Clock, first_ready_ms: int | None) -> None:
        t = np.ascontiguousarray(t_ms, dtype=np.int64)
        if values.shape != (len(t), len(names)):
            raise ValueError("feature values must have shape (rows, columns)")
        if len(t) and (np.any(np.diff(t) != HOUR_MS)):
            raise ValueError("feature rows must be a contiguous hourly grid")
        self._t = t
        self._names = names
        self._col = {n: i for i, n in enumerate(names)}
        self._values = np.ascontiguousarray(values, dtype=np.float64)
        self._clock = clock
        self._first_ready_ms = first_ready_ms

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    @property
    def first_ready_ms(self) -> int | None:
        """Manifest-level fact (the warm-up date), not a per-row value."""
        return self._first_ready_ms

    def _index(self, t_ms: int | None) -> int:
        now = self._clock.now_ms
        t = now if t_ms is None else int(t_ms)
        if t > now:
            raise LookAheadError(f"feature row {t} requested at decision time {now}")
        if not len(self._t) or t < self._t[0] or (t - int(self._t[0])) % HOUR_MS:
            raise KeyError(f"no feature row at {t}")
        i = (t - int(self._t[0])) // HOUR_MS
        if i >= len(self._t):
            raise KeyError(f"no feature row at {t}")
        return int(i)

    def value(self, name: str, t_ms: int | None = None) -> float:
        return float(self._values[self._index(t_ms), self._col[name]])

    def row(self, t_ms: int | None = None) -> dict[str, float]:
        i = self._index(t_ms)
        return {n: float(self._values[i, j]) for n, j in self._col.items()}

    def history(self, name: str, n: int, t_ms: int | None = None) -> np.ndarray:
        """The last ``n`` values of ``name`` up to and including ``t_ms`` (default: now), oldest first."""
        i = self._index(t_ms)
        return self._values[max(i - n + 1, 0) : i + 1, self._col[name]].copy()


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    equity: float
    wallet: float
    side: int  # +1 long, -1 short, 0 flat
    qty: float
    entry_price: float
    unrealized: float
    available_margin: float  # wallet minus the position margin (isolated)
    order_pending: bool


@dataclass(frozen=True, slots=True)
class DecisionContext:
    now_ms: int
    index: int
    features: FeatureView
    portfolio: PortfolioSnapshot
    period: str


@dataclass(frozen=True, slots=True)
class PrepareInfo:
    """Time-only facts a provider may use to plan (never prices): the decision grid and the window end."""

    grid_ms: np.ndarray
    window_end_ms: int
    first_ready_ms: int | None


class SignalProvider(Protocol):
    def describe(self) -> dict[str, Any]:
        """Name and parameters (canonical, JSON-serialisable); recorded in the run manifest."""
        ...

    def prepare(self, info: PrepareInfo) -> None: ...

    def decide(self, ctx: DecisionContext) -> Signal | None: ...
