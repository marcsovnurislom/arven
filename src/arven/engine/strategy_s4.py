"""Strategy S4 - "Impulse-Retest" (`docs/strategy_impulse_retest.md`, written before this file - every
threshold/parameter here mirrors that spec exactly; none of it is tuned to data, per CLAUDE.md's "do not
optimise parameters" and the spec's own pre-registration).

Swing/impulse/zone/trendline/trigger detection (spec sections 2-7) is pure computation over raw,
causally-truncated bar history: the caller truncates a `core.series.BarSeries` with
`.available_until(t)` first (already exactly "what was known at t" - CLAUDE.md rule 1), and every function
below just computes over whatever arrays it is handed, with no sense of time of its own. This mirrors
Stage 3's own "truncate first, then compute, causality falls out for free" idiom. The one exception is the
4h context filter (spec section 1.1), which is a single `MultiTFView` row lookup (an already-computed
feature, `engine.features`' own `ema_slope_50`), not a second parallel trend computation - that lookup is
not in this module (it has no `MultiTFView` dependency), it belongs to whatever builds a full decision
from a `MultiTFView` snapshot (`arven.backtest.strategy_s4_provider`).

This module produces an `ImpulseRetestDecision`, never a `core.signal.Signal`/`EngineSignal` - rendering a
decision into either of those is `arven.backtest.strategy_s4_provider`'s job, kept separate so the
technical-analysis math here stays hand-testable in complete isolation from any execution/signal plumbing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from arven.features import indicators as ind

# Spec section 2-8 parameters - fixed before any evaluation, never fitted.
SWING_K = 2
IMPULSE_ATR_MULT = 3.0
BASE_CANDLE_ATR_MULT = 1.0
STOP_ATR_BUFFER = 0.25
ATR_PERIOD = 14
FIB_ZONE_LOW = 0.5
FIB_ZONE_HIGH = 0.618
FIB_EXTENSIONS = (1.0, 1.414, 1.618)
CLOSE_FRACTIONS = (0.5, 0.3, 0.2)


def setup_tf_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Wilder ATR(14) of `setup_tf`, the one place this module touches `arven.features` - kept here
    (`arven.engine` may import `arven.features`, the same precedent `engine.features.py` already set in
    Phase 2) rather than in the `SignalProvider` adapter: `arven.backtest` must never import
    `arven.features` at all (a pre-existing, package-wide rule from Stage 4, `test_backtest_static_rules.
    py` - found while wiring this strategy in, not weakened to work around it)."""
    return ind.atr(high, low, close, ATR_PERIOD, ATR_PERIOD)


class SwingKind(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class Swing:
    index: int
    kind: SwingKind
    price: float
    confirmed_at: int  # index + K: the earliest bar index at which this swing is causally known


def confirmed_swings(high: np.ndarray, low: np.ndarray, k: int = SWING_K) -> tuple[Swing, ...]:
    """Every causal swing high/low in ``high``/``low`` (spec section 2): bar ``i`` is a swing high if it is
    strictly higher than every one of the ``k`` bars on both sides, confirmed (knowable) only once bar
    ``i + k`` has closed. A bar adjacent to a NaN is never flagged (NaN comparisons are always false), which
    is the safe, not a special-cased, behaviour."""
    if k < 1:
        raise ValueError("k must be >= 1")
    n = len(high)
    swings: list[Swing] = []
    for i in range(k, n - k):
        if np.all(high[i] > high[i - k : i]) and np.all(high[i] > high[i + 1 : i + k + 1]):
            swings.append(Swing(i, SwingKind.HIGH, float(high[i]), i + k))
        if np.all(low[i] < low[i - k : i]) and np.all(low[i] < low[i + 1 : i + k + 1]):
            swings.append(Swing(i, SwingKind.LOW, float(low[i]), i + k))
    return tuple(sorted(swings, key=lambda s: s.index))


@dataclass(frozen=True, slots=True)
class Impulse:
    start: Swing
    end: Swing
    side: int  # +1 bullish (low -> high), -1 bearish (high -> low)
    size: float  # |end.price - start.price|, > 0


def find_last_impulse(
    swings: tuple[Swing, ...], atr: np.ndarray, as_of_index: int, m: float = IMPULSE_ATR_MULT,
) -> Impulse | None:
    """The most recently *confirmed* swing-to-swing leg (searching backward) whose size qualifies
    (spec section 3) - using only swings with ``confirmed_at <= as_of_index`` (causal)."""
    available = [s for s in swings if s.confirmed_at <= as_of_index]
    for j in range(len(available) - 1, 0, -1):
        end, start = available[j], available[j - 1]
        if end.kind == start.kind:
            continue  # need an alternating high/low pair to form a leg
        side = 1 if start.kind == SwingKind.LOW else -1
        size = abs(end.price - start.price)
        a = atr[end.index] if end.index < len(atr) else math.nan
        if math.isfinite(a) and a > 0 and size >= m * a:
            return Impulse(start, end, side, size)
    return None


@dataclass(frozen=True, slots=True)
class Zone:
    lower: float
    upper: float
    fib_lower: float  # the un-intersected Fibonacci band, for the confidence computation
    fib_upper: float

    @property
    def overlap_fraction(self) -> float:
        width = self.fib_upper - self.fib_lower
        return 1.0 if width <= 0 else (self.upper - self.lower) / width


def confluence_zone(
    impulse: Impulse, high: np.ndarray, low: np.ndarray, atr: np.ndarray, n: float = BASE_CANDLE_ATR_MULT,
) -> Zone | None:
    """Fibonacci 0.5-0.618 retracement band of ``impulse``, intersected with a qualifying base candle's
    range - ``None`` if no bar qualifies (spec section 4) or the two bands do not actually overlap.

    The base candle is searched for *within the impulse leg itself* (``start.index`` to ``end.index``
    inclusive), nearest the impulse's end first - not fixed at ``start.index - 1`` (that was this
    function's original definition; found, before any evaluation ran, to geometrically never overlap the
    Fibonacci band for a real impulsive leg, since that band sits 38-50% of the way *up* the move from the
    origin - see the spec's own "Revision" note in section 4)."""
    end, start = impulse.end, impulse.start
    if impulse.side == 1:
        fib_lo, fib_hi = end.price - FIB_ZONE_HIGH * impulse.size, end.price - FIB_ZONE_LOW * impulse.size
    else:
        fib_lo, fib_hi = end.price + FIB_ZONE_LOW * impulse.size, end.price + FIB_ZONE_HIGH * impulse.size
    for i in range(end.index, start.index - 1, -1):
        a = atr[i]
        base_range = high[i] - low[i]
        if not (math.isfinite(a) and a > 0 and math.isfinite(base_range) and base_range >= n * a):
            continue
        lower, upper = max(fib_lo, low[i]), min(fib_hi, high[i])
        if lower < upper:
            return Zone(float(lower), float(upper), float(fib_lo), float(fib_hi))
    return None


@dataclass(frozen=True, slots=True)
class TrendLine:
    """Prices at real epoch-ms times, never bar indices - the trendline is built from ``setup_tf`` pivots
    but ``find_trigger`` must evaluate it on ``trigger_tf`` bars, a *different* index space (a 1h bar index
    10 and a 15m bar index 10 are ten hours apart vs. 150 minutes apart). Using indices directly here was a
    real bug found before this was ever wired to a second timeframe - see `docs/current_state.md`'s
    "Phase 7b" section."""

    t1_ms: int
    p1: float
    t2_ms: int
    p2: float

    def price_at(self, t_ms: int) -> float:
        if self.t2_ms == self.t1_ms:
            return self.p2
        return self.p1 + (self.p2 - self.p1) * (t_ms - self.t1_ms) / (self.t2_ms - self.t1_ms)


def counter_trend_trendline(
    swings: tuple[Swing, ...], impulse: Impulse, as_of_index: int, bar_times_ms: np.ndarray,
) -> TrendLine | None:
    """A line through the last two confirmed counter-trend pivots since the impulse's end (spec section
    5) - ``None`` if fewer than two exist yet. ``bar_times_ms`` is the *same* ``setup_tf`` array the
    pivots' own ``index`` values refer to (e.g. ``BarSeries.open_time_ms``), converting index -> real time
    once here so every other function downstream only ever deals in real time."""
    counter_kind = SwingKind.HIGH if impulse.side == 1 else SwingKind.LOW
    pivots = [
        s for s in swings
        if s.kind == counter_kind and s.index > impulse.end.index and s.confirmed_at <= as_of_index
    ]
    if len(pivots) < 2:
        return None
    p1, p2 = pivots[-2], pivots[-1]
    return TrendLine(int(bar_times_ms[p1.index]), p1.price, int(bar_times_ms[p2.index]), p2.price)


def find_trigger(
    close: np.ndarray, high: np.ndarray, low: np.ndarray, bar_times_ms: np.ndarray, trendline: TrendLine,
    zone: Zone, side: int, search_from_index: int,
) -> int | None:
    """First `trigger_tf` bar index at or after ``search_from_index`` where an earlier-or-same bar closed
    beyond the trendline *and* this bar's low/high (long/short) touches the zone while its own close holds
    beyond the zone's near edge (spec section 6) - ``None`` if not yet triggered within the given arrays.
    ``bar_times_ms`` is ``trigger_tf``'s own bar-time array (e.g. ``BarSeries.open_time_ms``), used to
    evaluate the (``setup_tf``-built) ``trendline`` at this timeframe's own real times."""
    broke = False
    for i in range(search_from_index, len(close)):
        line_price = trendline.price_at(int(bar_times_ms[i]))
        if side == 1:
            broke = broke or close[i] > line_price
            if broke and low[i] <= zone.upper and close[i] >= zone.lower:
                return i
        else:
            broke = broke or close[i] < line_price
            if broke and high[i] >= zone.lower and close[i] <= zone.upper:
                return i
    return None


@dataclass(frozen=True, slots=True)
class TargetLevel:
    fib: float
    price: float
    r_multiple: float
    close_fraction: float


@dataclass(frozen=True, eq=False)
class ImpulseRetestDecision:
    side: int
    entry: float
    stop: float
    targets: tuple[TargetLevel, ...]
    confidence: float
    impulse: Impulse
    zone: Zone
    trigger_index: int


def build_decision(impulse: Impulse, zone: Zone, entry_price: float, atr_at_entry: float, trigger_index: int) -> ImpulseRetestDecision:
    """Stop and targets from the impulse/zone geometry (spec section 7); confidence from how much of the
    Fibonacci band the base-candle zone actually covers (section 8), clamped to ``[0.1, 1.0]`` so a thin
    overlap never reads as exactly zero."""
    side = impulse.side
    stop = zone.lower - STOP_ATR_BUFFER * atr_at_entry if side == 1 else zone.upper + STOP_ATR_BUFFER * atr_at_entry
    risk = abs(entry_price - stop)
    # r_multiple = side * (price - entry) / risk = side * (side * fib * size) / risk = fib * size / risk
    # (side**2 == 1 always) - a target is always a profit, so its R is always positive, long or short.
    targets = tuple(
        TargetLevel(fib, entry_price + side * fib * impulse.size, (fib * impulse.size) / risk, frac)
        for fib, frac in zip(FIB_EXTENSIONS, CLOSE_FRACTIONS, strict=True)
    )
    confidence = min(1.0, max(0.1, zone.overlap_fraction))
    return ImpulseRetestDecision(side, entry_price, stop, targets, confidence, impulse, zone, trigger_index)
