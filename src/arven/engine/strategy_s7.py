"""Strategy S7 - "Trend-Break Fib Retest", the owner's own method (`docs/strategy_s7_trend_break_fib.md`).

This module is the **pattern detector only** (spec sections 2.1-2.6): trendline with clustered touches, the break
(including the sideways-range rule), the Fibonacci leg with a moving level 1 that freezes on the first real pullback,
the 0.5-0.618 entry zone, and the confluence zones (order block, fair value gap, inverse FVG, prior swing levels).
Entries, stops and targets (spec sections 3-5) come later, after the owner has checked that the detector sees the
same pattern he does (spec section 8).

Causality: `detect_setups` walks the bars in time order and every decision at bar ``t`` uses only bars ``<= t``
(swings only once confirmed, ATR is a recursive average of the past). A setup is reported at its arming bar; running
the detector on data truncated after that bar yields exactly the same setup (tested). Shorts are the exact mirror:
the long detector runs on the price series reflected through zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from arven.features import indicators as ind

SWING_K = 2
ATR_PERIOD = 14


@dataclass(frozen=True, slots=True)
class S7Params:
    min_touches: int = 3
    touch_tol_atr: float = 0.25
    cluster_drop_atr: float = 1.0
    cluster_min_bars: int = 5
    count_every_touch: bool = False  # variant 9: True counts every touch instead of clusters
    range_min_bars: int = 12
    range_max_atr: float = 3.0
    range_impulse_body_atr: float = 1.0  # mandatory body of the bar completing a break out of a range
    impulse_body_atr: float | None = None  # variant 3: extra impulse rule for breaks without a range
    freeze_pullback: float = 0.236  # variant 4
    level0_range_bottom: bool = False  # variant 10
    lookback_bars: int = 400
    max_swings: int = 10
    max_leg_bars: int = 120
    ob_max_atr: float = 2.0
    ob_search_bars: int = 10
    # significance (definition choices made before the owner's visual check, no outcome data used): a trendline
    # must actually trend, and the break leg must be an impulse, not a wiggle inside chop
    min_line_drop_atr: float = 2.0
    min_leg_atr: float = 3.0
    max_level_zones: int = 3


@dataclass(frozen=True, slots=True)
class Line:
    a_index: int
    a_price: float
    slope: float  # price per bar

    def at(self, i: int | np.ndarray) -> float | np.ndarray:
        return self.a_price + self.slope * (np.asarray(i) - self.a_index)


@dataclass(frozen=True, slots=True)
class RangeBox:
    start: int
    end: int
    top: float
    bottom: float


@dataclass(frozen=True, slots=True)
class ConfluenceZone:
    kind: str  # "order_block" | "fvg" | "ifvg" | "level"
    low: float
    high: float
    index: int


@dataclass(frozen=True, slots=True)
class S7Setup:
    side: int
    line: Line
    touches: tuple[int, ...]
    last_touch: int
    h_last: float
    range_box: RangeBox | None
    cross_index: int  # first close beyond the line
    break_index: int  # bar that completed the break
    level0_index: int
    level0: float
    level1_index: int
    level1: float
    arm_index: int
    zone_low: float
    zone_high: float
    confluence: tuple[ConfluenceZone, ...] = field(default_factory=tuple)

    def fib(self, ratio: float) -> float:
        return self.level0 + self.side * ratio * abs(self.level1 - self.level0)

    @property
    def confluence_score(self) -> int:
        return len({z.kind for z in self.confluence})


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    return ind.atr(high, low, close, ATR_PERIOD, ATR_PERIOD)


def _swing_highs(high: np.ndarray, k: int = SWING_K) -> np.ndarray:
    """Indices ``i`` that are strict swing highs (higher than ``k`` bars on each side); confirmed at ``i + k``."""
    n = len(high)
    ok = np.ones(n, dtype=bool)
    for s in range(1, k + 1):
        left = np.full(n, -np.inf)
        right = np.full(n, -np.inf)
        left[s:] = high[:-s]
        right[: n - s] = high[s:]
        ok &= (high > left) & (high > right)
    ok[:k] = False
    ok[n - k :] = False
    return np.flatnonzero(ok)


def _swing_lows(low: np.ndarray, k: int = SWING_K) -> np.ndarray:
    return _swing_highs(-low, k)


def _count_touches(line: Line, swings: np.ndarray, high: np.ndarray, low: np.ndarray, a_tr: np.ndarray, p: S7Params) -> list[int]:
    """Swing highs within tolerance of the line, counted as clusters (spec 2.5) unless every touch counts."""
    counted: list[int] = []
    for s in swings:
        s = int(s)
        if s < line.a_index or not math.isfinite(a_tr[s]):
            continue
        if abs(high[s] - float(line.at(s))) > p.touch_tol_atr * a_tr[s]:
            continue
        if not counted or p.count_every_touch:
            counted.append(s)
            continue
        prev = counted[-1]
        if s - prev < p.cluster_min_bars:
            continue
        seg = np.arange(prev + 1, s)
        dips = (line.at(seg) - low[prev + 1 : s]) / a_tr[prev + 1 : s]
        if seg.size and np.nanmax(dips) >= p.cluster_drop_atr:
            counted.append(s)
    return counted


def _best_line(t: int, from_index: int, swing_highs: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, a_tr: np.ndarray, p: S7Params) -> tuple[Line, list[int]] | None:
    """The descending line with the most counted touches among the recent confirmed swing highs, respected by every
    close since its first anchor (a close above the line by more than the tolerance disqualifies it)."""
    known = swing_highs[(swing_highs + SWING_K <= t) & (swing_highs >= max(from_index, t - p.lookback_bars))]
    if len(known) < 2:
        return None
    recent = known[-p.max_swings :]
    best: tuple[int, int, Line, list[int]] | None = None
    for ia in range(len(recent) - 1):
        a = int(recent[ia])
        for ib in range(ia + 1, len(recent)):
            b = int(recent[ib])
            if high[b] >= high[a]:
                continue
            line = Line(a, float(high[a]), float((high[b] - high[a]) / (b - a)))
            seg = np.arange(a, t)  # bars before t: bar t itself may be the one that crosses the line
            tol = p.touch_tol_atr * np.nan_to_num(a_tr[a:t], nan=np.inf)
            if np.any(close[a:t] > line.at(seg) + tol):
                continue
            touches = _count_touches(line, known[known >= a], high, low, a_tr, p)
            if len(touches) < p.min_touches:
                continue
            if high[a] - high[touches[-1]] < p.min_line_drop_atr * a_tr[touches[-1]]:
                continue
            key = (len(touches), -a)
            if best is None or key > (best[0], best[1]):
                best = (len(touches), -a, line, touches)
    return None if best is None else (best[2], best[3])


def _range_before(t: int, high: np.ndarray, low: np.ndarray, a_tr: np.ndarray, p: S7Params) -> RangeBox | None:
    """The longest run of bars ending at ``t - 1`` that fits in a band of at most ``range_max_atr`` ATR."""
    if t < 1 or not math.isfinite(a_tr[t - 1]):
        return None
    limit = p.range_max_atr * a_tr[t - 1]
    hi, lo = -np.inf, np.inf
    j = t - 1
    while j >= 0:
        hi2, lo2 = max(hi, high[j]), min(lo, low[j])
        if hi2 - lo2 > limit:
            break
        hi, lo = hi2, lo2
        j -= 1
    length = (t - 1) - j
    return RangeBox(j + 1, t - 1, float(hi), float(lo)) if length >= p.range_min_bars else None


def _confluence(s: S7Setup, t: int, o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, a_tr: np.ndarray, p: S7Params) -> tuple[ConfluenceZone, ...]:
    """Zones known at bar ``t`` that overlap the entry zone widened by the touch tolerance (long orientation)."""
    pad = p.touch_tol_atr * a_tr[t]
    zl, zh = s.zone_low - pad, s.zone_high + pad
    out: list[ConfluenceZone] = []
    overlaps = lambda a, b: a <= zh and b >= zl  # noqa: E731
    for j in range(s.level0_index, max(-1, s.level0_index - p.ob_search_bars), -1):
        if c[j] < o[j]:
            if h[j] - lo[j] <= p.ob_max_atr * a_tr[j] and overlaps(lo[j], h[j]):
                out.append(ConfluenceZone("order_block", float(lo[j]), float(h[j]), j))
            break
    for i in range(s.level0_index + 2, t + 1):
        if lo[i] > h[i - 2]:
            bottom, top = float(h[i - 2]), float(lo[i])
            filled = i < t and np.min(lo[i + 1 : t + 1]) <= bottom
            if not filled and overlaps(bottom, top):
                out.append(ConfluenceZone("fvg", bottom, top, i))
    for i in range(max(2, s.last_touch), s.break_index + 1):
        if h[i] < lo[i - 2]:
            bottom, top = float(h[i]), float(lo[i - 2])
            if i < t and np.any(c[i + 1 : t + 1] > top) and overlaps(bottom, top):
                out.append(ConfluenceZone("ifvg", bottom, top, i))
    levels: list[ConfluenceZone] = []
    for sw in _swing_highs(h[: t + 1]):
        if sw + SWING_K <= t and sw < s.level0_index and overlaps(h[sw], h[sw]):
            levels.append(ConfluenceZone("level", float(h[sw]), float(h[sw]), int(sw)))
    for sw in _swing_lows(lo[: t + 1]):
        if sw + SWING_K <= t and sw < s.level0_index and overlaps(lo[sw], lo[sw]):
            levels.append(ConfluenceZone("level", float(lo[sw]), float(lo[sw]), int(sw)))
    # keep the most recent few prior swing levels only (older chop would otherwise flood the list)
    out.extend(sorted(levels, key=lambda z: -z.index)[: p.max_level_zones])
    return tuple(out)


def _detect_long(o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, p: S7Params, start: int = 0) -> list[S7Setup]:
    n = len(c)
    a_tr = atr(h, lo, c)
    swings = _swing_highs(h)
    swing_conf = set(int(s) + SWING_K for s in swings)
    out: list[S7Setup] = []
    phase = "seek"
    line: Line | None = None
    touches: list[int] = []
    search_from = 0
    pending: dict = {}
    leg: dict = {}
    for t in range(max(start, ATR_PERIOD + 2), n):
        if not math.isfinite(a_tr[t]):
            continue
        if phase == "seek":
            if t in swing_conf:  # candidate lines only change when a new swing high is confirmed
                found = _best_line(t, search_from, swings, h, lo, c, a_tr, p)
                if found is not None:
                    line, touches = found
            if line is None:
                continue
            if c[t] > float(line.at(t)) + p.touch_tol_atr * a_tr[t]:
                last = touches[-1]
                rng = _range_before(t, h, lo, a_tr, p)
                required = max(float(h[last]), rng.top if rng else -np.inf)
                pending = {"cross": t, "last": last, "h_last": float(h[last]), "range": rng, "required": required,
                           "cancel_below": rng.bottom if rng else float(np.min(lo[last : t + 1])), "touches": tuple(touches), "line": line}
                phase = "pending"
            else:
                continue
        if phase == "pending":
            if c[t] < pending["cancel_below"]:
                phase, line, search_from = "seek", None, t
                continue
            body = abs(c[t] - o[t])
            body_need = p.range_impulse_body_atr if pending["range"] is not None else p.impulse_body_atr
            if c[t] >= pending["required"] and (body_need is None or body >= body_need * a_tr[t]):
                last = pending["last"]
                rng = pending["range"]
                l0_idx = last + int(np.argmin(lo[last : t + 1]))
                level0 = float(lo[l0_idx])
                if p.level0_range_bottom and rng is not None:
                    level0, l0_idx = rng.bottom, rng.start + int(np.argmin(lo[rng.start : rng.end + 1]))
                leg = {"break": t, "l0_idx": l0_idx, "level0": level0, "l1_idx": t, "level1": float(c[t])}
                phase = "leg"
            continue
        if phase == "leg":
            if c[t] > leg["level1"]:
                leg["level1"], leg["l1_idx"] = float(c[t]), t
            if c[t] < leg["level0"] or t - leg["break"] > p.max_leg_bars:
                phase, line, search_from = "seek", None, t
                continue
            span = leg["level1"] - leg["level0"]
            if t > leg["l1_idx"] and span > 0 and lo[t] <= leg["level1"] - p.freeze_pullback * span:
                if span < p.min_leg_atr * a_tr[t]:
                    phase, line, search_from = "seek", None, leg["break"]  # a wiggle, not an impulse leg
                    continue
                setup = S7Setup(
                    side=1, line=pending["line"], touches=pending["touches"], last_touch=pending["last"], h_last=pending["h_last"],
                    range_box=pending["range"], cross_index=pending["cross"], break_index=leg["break"], level0_index=leg["l0_idx"],
                    level0=leg["level0"], level1_index=leg["l1_idx"], level1=leg["level1"], arm_index=t,
                    zone_low=leg["level1"] - 0.618 * span, zone_high=leg["level1"] - 0.5 * span,
                )
                out.append(replace(setup, confluence=_confluence(setup, t, o, h, lo, c, a_tr, p)))
                phase, line, search_from = "seek", None, leg["break"]
    return out


def _mirror_setup(s: S7Setup) -> S7Setup:
    neg = lambda z: ConfluenceZone(z.kind, -z.high, -z.low, z.index)  # noqa: E731
    return replace(
        s, side=-1, line=Line(s.line.a_index, -s.line.a_price, -s.line.slope), h_last=-s.h_last,
        range_box=None if s.range_box is None else RangeBox(s.range_box.start, s.range_box.end, -s.range_box.bottom, -s.range_box.top),
        level0=-s.level0, level1=-s.level1, zone_low=-s.zone_high, zone_high=-s.zone_low, confluence=tuple(neg(z) for z in s.confluence),
    )


def detect_setups(o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, params: S7Params | None = None, start: int = 0) -> list[S7Setup]:
    """All armed long and short setups, in arming order. Shorts: the long detector on the reflected series."""
    p = params or S7Params()
    o, h, lo, c = (np.asarray(x, dtype=float) for x in (o, h, lo, c))
    longs = _detect_long(o, h, lo, c, p, start)
    shorts = [_mirror_setup(s) for s in _detect_long(-o, -lo, -h, -c, p, start)]
    return sorted(longs + shorts, key=lambda s: (s.arm_index, s.side))
