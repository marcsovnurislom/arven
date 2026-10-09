"""Strategy S5 - "Squeeze-Breakout" (`docs/strategy_range_breakout.md`, written before this file; every
parameter mirrors that spec and is never fitted). Pure math over causally-truncated bar arrays - the caller
truncates with ``BarSeries.available_until`` first ("truncate first, then compute"); the 4h context slope is
looked up by the provider, not here. Produces a ``RangeBreakoutDecision``; rendering it into a ``Signal`` or
``EngineSignal`` is ``arven.backtest.strategy_s5_provider``'s job."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from arven.features import indicators as ind

RANGE_BARS = 24
ATR_PERIOD = 14
ATR_WINDOW = 300
SQUEEZE_MAX_ATR = 4.0
BREAK_BUFFER_ATR = 0.1
STOP_ATR_BUFFER = 0.25
TARGET_WIDTHS = (1.0, 1.5, 2.0)
CLOSE_FRACTIONS = (0.5, 0.3, 0.2)
MIN_SETUP_BARS = 200


@dataclass(frozen=True, slots=True)
class RangeState:
    hi: float
    lo: float
    atr: float

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def mid(self) -> float:
        return (self.hi + self.lo) / 2.0

    @property
    def buffer(self) -> float:
        return BREAK_BUFFER_ATR * self.atr


def squeeze_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> RangeState | None:
    """The squeeze range of the last ``RANGE_BARS`` closed bars, or ``None`` if there is too little history,
    the data is not finite, or the range is not tight enough (``width <= SQUEEZE_MAX_ATR * ATR``)."""
    n = len(close)
    if n < max(RANGE_BARS, ATR_PERIOD + 1):
        return None
    w = slice(max(0, n - ATR_WINDOW), n)
    atr = float(ind.atr(high[w], low[w], close[w], ATR_PERIOD, ATR_PERIOD)[-1])
    hi, lo = float(np.max(high[n - RANGE_BARS :])), float(np.min(low[n - RANGE_BARS :]))
    if not (math.isfinite(atr) and math.isfinite(hi) and math.isfinite(lo)) or atr <= 0 or hi <= lo:
        return None
    state = RangeState(hi, lo, atr)
    return state if state.width <= SQUEEZE_MAX_ATR * atr else None


def breakout_side(close_now: float, close_prev: float, state: RangeState, slope: float) -> int:
    """+1 / -1 for a fresh close beyond the range edge in the direction of the 4h slope, else 0."""
    if not (math.isfinite(close_now) and math.isfinite(close_prev) and math.isfinite(slope)):
        return 0
    up, down = state.hi + state.buffer, state.lo - state.buffer
    if slope > 0 and close_now > up and close_prev <= up:
        return 1
    if slope < 0 and close_now < down and close_prev >= down:
        return -1
    return 0


@dataclass(frozen=True, slots=True)
class TargetLevel:
    width_multiple: float
    price: float
    r_multiple: float
    close_fraction: float


@dataclass(frozen=True, eq=False)
class RangeBreakoutDecision:
    side: int
    entry: float
    stop: float
    targets: tuple[TargetLevel, ...]
    confidence: float
    state: RangeState


def build_decision(side: int, entry: float, state: RangeState) -> RangeBreakoutDecision | None:
    stop = state.mid - STOP_ATR_BUFFER * state.atr if side == 1 else state.mid + STOP_ATR_BUFFER * state.atr
    risk = abs(entry - stop)
    if not (math.isfinite(risk) and risk > 0):
        return None
    targets = tuple(
        TargetLevel(k, entry + side * k * state.width, k * state.width / risk, frac)
        for k, frac in zip(TARGET_WIDTHS, CLOSE_FRACTIONS, strict=True)
    )
    confidence = min(1.0, max(0.1, 1.0 - state.width / (SQUEEZE_MAX_ATR * state.atr)))
    return RangeBreakoutDecision(side, entry, stop, targets, confidence, state)
