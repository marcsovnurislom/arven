"""Strategy S7 trade plan - entry, stop, targets and the pre-entry cancellation rules
(`docs/strategy_s7_trend_break_fib.md` sections 3-5).

Pure functions of an armed :class:`~arven.engine.strategy_s7.S7Setup` and of bars that have already closed: no fills,
no fees, no slippage (those belong to ``arven.backtest``), so the same plan can drive the backtest simulator now and a
live provider later (CLAUDE.md rule 8).

**Orientation.** Like the detector, the rules are written for a long and applied to shorts on reflected prices:
:func:`oriented_bars` turns raw ``(open, high, low, close)`` into the long orientation (``side * price``, high and low
swapped for shorts), and :class:`OrientedSetup` holds the setup's levels in the same orientation. "Below" always means
"against the trade".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from arven.engine.strategy_s7 import S7Params, S7Setup, zone_broken_by_impulse

ENTRIES = ("E1", "E2", "E3", "E4")
# trade management after entry (owner, 2026-10-11: "trades that nearly reached TP then hit the stop", "trades that ran 2-3x
# past TP3"): V0 = as evaluated; BE_TP1 = stop to entry after TP1; LADDER = stop to entry after TP1 and to TP1 after TP2;
# PRE_BE_LADDER = LADDER plus a breakeven move once price has covered 70 % of the way to TP1; RUNNER = LADDER with the last
# 20 % split 10 % at fib 2.0 and 10 % at fib 3.0 (stop to TP2 after fib 2.0)
MANAGEMENTS = ("V0", "BE_TP1", "LADDER", "PRE_BE_LADDER", "RUNNER")
STOPS = ("S1", "S2", "S3")
TP_FRACTIONS = (0.5, 0.3, 0.2)


@dataclass(frozen=True, slots=True)
class S7TradeParams:
    entry: str = "E1"  # variant 5
    stop: str = "S2"  # variant 6
    breakeven_after_tp1: bool = False  # variant 7
    min_tp1_r: float | None = None  # variant 8: skip the trade if TP1 is nearer than this many R from the fill
    s1_fib: float = 0.1  # S1: fib 0.1, just inside level 0
    s2_pad_atr: float = 0.25  # S2: level 0 minus 0.25 ATR
    s3_hard_atr: float = 1.0  # S3: hard stop at level 0 minus 1 ATR (plus the close-based exit)
    tp2_band: tuple[float, float] = (1.272, 1.618)  # TP2: nearest resistance inside this fib band, else its far end
    tp3_fib: float = 2.0
    management: str = "V0"
    pre_be_fraction: float = 0.7  # PRE_BE_LADDER: breakeven once price covered this share of the way to TP1
    runner_fib: float = 3.0  # RUNNER: the last rung

    def __post_init__(self) -> None:
        if self.management not in MANAGEMENTS:
            raise ValueError(f"management must be one of {MANAGEMENTS}")
        if self.entry not in ENTRIES:
            raise ValueError(f"entry must be one of {ENTRIES}")
        if self.stop not in STOPS:
            raise ValueError(f"stop must be one of {STOPS}")


@dataclass(frozen=True, slots=True)
class OrientedSetup:
    """The setup's levels in the long orientation (``side * price``)."""

    side: int
    level0: float
    level1: float
    zone_far: float  # the zone edge farther from level 1 (the "whole zone" is broken below it)
    zone_near: float  # the edge nearer to level 1 (the zone is reached when price trades down to it)
    mid: float  # fib 0.5, the E1 rejection level (the same price in both zone conventions)


def orient(s: S7Setup) -> OrientedSetup:
    far, near = (s.zone_low, s.zone_high) if s.side == 1 else (s.zone_high, s.zone_low)
    k = s.side
    return OrientedSetup(k, k * s.level0, k * s.level1, k * far, k * near, k * s.fib(0.5))


def oriented_bars(side: int, o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return (o, h, lo, c) if side == 1 else (-o, -lo, -h, -c)


def stop_price(s: S7Setup, tp: S7TradeParams) -> float:
    """The protective stop in raw prices (for S3 the hard stop; its close-based exit is :func:`s3_exit_index`)."""
    if tp.stop == "S1":
        return s.fib(tp.s1_fib)
    pad = tp.s2_pad_atr if tp.stop == "S2" else tp.s3_hard_atr
    return s.level0 - s.side * pad * s.atr


def limit_orders(s: S7Setup, tp: S7TradeParams) -> tuple[tuple[float, float], ...]:
    """``(raw limit price, size fraction)`` of the resting orders, nearest to price first; empty for E1."""
    mid, deep = s.fib(0.5), s.limit_618
    if tp.entry == "E1":
        return ()
    if tp.entry == "E2":
        return ((deep, 1.0),)
    if tp.entry == "E3":
        return ((mid, 1.0),)
    pair = sorted(((mid, 0.5), (deep, 0.5)), key=lambda x: -s.side * x[0])
    return tuple(pair)


def e1_trigger(os_: OrientedSetup, low: np.ndarray, close: np.ndarray, touched: bool) -> tuple[int | None, bool]:
    """E1 on oriented lower-timeframe bars: the first bar ``k`` such that the zone has been reached (a low at or below
    its near edge, on bar ``k`` or earlier) and bar ``k`` closes back above fib 0.5. Returns ``(k or None, touched)``
    so a caller can carry the "zone reached" state across windows."""
    for k in range(len(close)):
        if low[k] <= os_.zone_near:
            touched = True
        if touched and close[k] > os_.mid:
            return k, True
    return None, touched


def tf_cancel_reason(
    os_: OrientedSetup, j: int, o: np.ndarray, lo: np.ndarray, c: np.ndarray, v: np.ndarray | None, a_tr: np.ndarray, p: S7Params,
) -> str | None:
    """Why the closed TF bar ``j`` (oriented arrays) cancels a setup that has not been entered yet, or ``None``
    (spec section 3; the expiry after ``cancel_after_mult`` x the break-to-arm duration is the caller's loop bound)."""
    if c[j] < os_.level0:
        return "closed_below_level0"
    if zone_broken_by_impulse(j, o, lo, c, v, a_tr, os_.zone_far, p):
        return "zone_broken_by_impulse"
    if c[j] > os_.level1:
        return "level1_moved"  # the detector re-arms the leg with the new level 1 (a new setup)
    return None


def s3_exit_index(os_: OrientedSetup, c: np.ndarray, start: int) -> int | None:
    """S3: the first TF bar at or after ``start`` that closes below level 0 (oriented closes); exit at the next open."""
    below = np.flatnonzero(c[start:] < os_.level0)
    return None if below.size == 0 else start + int(below[0])


def targets(s: S7Setup, tp: S7TradeParams, resistances: np.ndarray) -> tuple[tuple[float, float], ...]:
    """``(raw price, close fraction)`` for TP1 (fib 1.0), TP2 (the nearest known resistance inside the fib band, else the
    band's far end) and TP3 (fib 2.0). ``resistances`` are raw prices of prior confirmed swing highs (lows for shorts)
    already known at the arming bar; the caller is responsible for that causality."""
    k = s.side
    lo_b, hi_b = k * s.fib(tp.tp2_band[0]), k * s.fib(tp.tp2_band[1])
    r = k * np.asarray(resistances, dtype=float)
    inside = r[(r >= lo_b) & (r <= hi_b)]
    tp2 = s.fib(tp.tp2_band[1]) if inside.size == 0 else k * float(inside.min())
    prices = (s.fib(1.0), tp2, s.fib(tp.tp3_fib))
    return tuple(zip(prices, TP_FRACTIONS, strict=True))


def management_plan(s: S7Setup, tp: S7TradeParams, fill: float, prices: tuple[float, ...], fracs: tuple[float, ...]) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float | None, ...] | None, float | None]:
    """``(target prices, close fractions, stop after each rung, breakeven trigger in R or None)`` for ``tp.management``.
    ``prices``/``fracs`` are the plain TP1-TP3 plan; the breakeven trigger is in R of the actual fill (for the tracker)."""
    if tp.management == "V0":
        return prices, fracs, None, None
    if tp.management == "BE_TP1":
        return prices, fracs, (fill, None, None), None
    ladder = (fill, prices[0], None)
    if tp.management == "LADDER":
        return prices, fracs, ladder, None
    if tp.management == "PRE_BE_LADDER":
        risk = abs(fill - stop_price(s, tp))
        return prices, fracs, ladder, tp.pre_be_fraction * abs(prices[0] - fill) / risk
    # RUNNER
    return (prices[0], prices[1], s.fib(tp.tp3_fib), s.fib(tp.runner_fib)), (0.5, 0.3, 0.1, 0.1), (fill, prices[0], prices[1], None), None


def ladder_r(fill: float, stop: float, side: int, prices: tuple[float, ...]) -> tuple[float, ...] | None:
    """R-multiples of the target prices from an actual fill, or ``None`` if the geometry is invalid (fill at or beyond
    the stop, or a target not strictly beyond the previous one / the fill)."""
    risk = side * (fill - stop)
    if not (math.isfinite(risk) and risk > 0):
        return None
    rs = tuple(side * (p - fill) / risk for p in prices)
    if rs[0] <= 0 or any(b <= a for a, b in zip(rs, rs[1:])):
        return None
    return rs
