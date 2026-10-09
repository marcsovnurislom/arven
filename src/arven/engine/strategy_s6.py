"""Strategy S6 - "Trend-Pullback" (`docs/strategy_trend_pullback.md`, written before this file; parameters mirror
that spec and are never fitted). Pure math over causally-truncated arrays (the caller truncates with
``BarSeries.available_until`` first); the 4h slope lookup lives in the provider."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from arven.features import indicators as ind

EMA_PERIOD = 20
ATR_PERIOD = 14
TRAIL_BARS = 300
PULLBACK_WINDOW = 8
PULLBACK_ATR_TOUCH = 0.25
STOP_ATR_BUFFER = 0.25
MIN_STOP_ATR = 1.0
BOUNCE_BARS = 4
TARGET_R = (1.5, 2.5, 4.0)
CLOSE_FRACTIONS = (0.5, 0.3, 0.2)
COOLDOWN_HOURS = 8
MIN_SETUP_BARS = 200


@dataclass(frozen=True, slots=True)
class PullbackState:
    ema: float
    atr: float
    last_close: float
    pull_low: float
    pull_high: float


def pullback_state(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> PullbackState | None:
    n = len(close)
    if n < max(PULLBACK_WINDOW, ATR_PERIOD + 1, EMA_PERIOD):
        return None
    w = slice(max(0, n - TRAIL_BARS), n)
    atr = float(ind.atr(high[w], low[w], close[w], ATR_PERIOD, ATR_PERIOD)[-1])
    ema = float(ind.ema(close[w], EMA_PERIOD, EMA_PERIOD)[-1])
    state = PullbackState(
        ema, atr, float(close[-1]), float(np.min(low[n - PULLBACK_WINDOW :])), float(np.max(high[n - PULLBACK_WINDOW :])),
    )
    if not all(math.isfinite(v) for v in (state.ema, state.atr, state.last_close, state.pull_low, state.pull_high)) or state.atr <= 0:
        return None
    return state


def pullback_ok(side: int, s: PullbackState) -> bool:
    """Long: price came down to the average and still holds above it; short mirrored."""
    if side == 1:
        return s.pull_low <= s.ema + PULLBACK_ATR_TOUCH * s.atr and s.last_close > s.ema
    return s.pull_high >= s.ema - PULLBACK_ATR_TOUCH * s.atr and s.last_close < s.ema


def bounce_fires(side: int, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> bool:
    """Fresh close beyond the extreme of the previous ``BOUNCE_BARS`` closed 15m bars."""
    if len(close) < BOUNCE_BARS + 2:
        return False
    if side == 1:
        level_now, level_prev = float(np.max(high[-1 - BOUNCE_BARS : -1])), float(np.max(high[-2 - BOUNCE_BARS : -2]))
        return bool(close[-1] > level_now and not close[-2] > level_prev)
    level_now, level_prev = float(np.min(low[-1 - BOUNCE_BARS : -1])), float(np.min(low[-2 - BOUNCE_BARS : -2]))
    return bool(close[-1] < level_now and not close[-2] < level_prev)


@dataclass(frozen=True, slots=True)
class TargetLevel:
    r_multiple: float
    price: float
    close_fraction: float


@dataclass(frozen=True, eq=False)
class TrendPullbackDecision:
    side: int
    entry: float
    stop: float
    targets: tuple[TargetLevel, ...]
    confidence: float
    state: PullbackState


def build_decision(side: int, entry: float, s: PullbackState) -> TrendPullbackDecision | None:
    if side == 1:
        stop = min(s.pull_low - STOP_ATR_BUFFER * s.atr, entry - MIN_STOP_ATR * s.atr)
    else:
        stop = max(s.pull_high + STOP_ATR_BUFFER * s.atr, entry + MIN_STOP_ATR * s.atr)
    risk = abs(entry - stop)
    if not (math.isfinite(risk) and risk > 0):
        return None
    targets = tuple(TargetLevel(k, entry + side * k * risk, f) for k, f in zip(TARGET_R, CLOSE_FRACTIONS, strict=True))
    return TrendPullbackDecision(side, entry, stop, targets, 0.5, s)
