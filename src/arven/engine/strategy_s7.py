"""Strategy S7 - "Trend-Break Fib Retest", the owner's own method (`docs/strategy_s7_trend_break_fib.md`).

This module is the **pattern detector only** (spec sections 2.1-2.6): trendline with clustered touches, the break
(including the sideways-range rule), the Fibonacci leg with a moving level 1 that freezes on the first real pullback,
the 0.5-0.618 entry zone, and the confluence zones (order block, fair value gap, inverse FVG, prior swing levels).
Entries, stops and targets (spec sections 3-5) come later, after the owner has checked that the detector sees the
same pattern they do (spec section 8; round-1 rules from that check: crooked-line wick limit, the "beyond the line's
first anchor" flag/variant 11, the zone broken by an impulse, the zone already touched at arming).

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
    impulse_fvg: bool = False  # variant 3: the break bar must complete a 3-candle FVG (its low above the high 2 bars back)
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
    # owner's check of 100 development setups (spec section 8, round 1): a line whose candles poke through it by more
    # than this (wicks, between its first anchor and the break) is "crooked" (None switches the rule off)
    max_wick_pierce_atr: float | None = 0.8
    # variant 11: skip setups whose break leg rose above the line's first (highest) anchor - "all previous highs broken"
    skip_beyond_line_start: bool = True
    # owner's rule: an arming bar that runs through the whole entry zone with a big body or big volume cancels the setup
    zone_break_body_atr: float = 1.0
    zone_break_volume_mult: float = 2.0
    volume_median_bars: int = 20
    # owner's check, round 2 (both left to the data, owner's choice):
    # variant 12: the break is the first close beyond the line (no last-touch-high / range-top requirement)
    break_on_cross: bool = False
    # variant 13: the line must start at the highest confirmed swing high of the search window (the start of the move)
    line_from_major_high: bool = False
    # variant 14 (owner, 2026-10-11: "don't know, test both"): the entry zone as a retracement *from level 1*. Baseline:
    # 50-61.8 % back from level 1 (classic); variant: 38.2-50 % back, i.e. fib 0.5-0.618 counted *from level 0* (the
    # lines the review page drew). Fib 0.5 (the middle of the leg) is the same price in both.
    shallow_zone: bool = False
    # spec section 3: an armed setup lives this many times its break-to-arm duration (in TF bars) before it expires
    cancel_after_mult: int = 3


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
    beyond_line_start: bool = False  # the break leg's high rose above the line's first anchor (variant 11)
    zone_touched_at_arm: bool = False  # the arming bar already reached the entry zone (within the touch tolerance)
    limit_618: float = math.nan  # the "fib 0.618" limit price of the zone convention in use (E2; variant 14)
    atr: float = math.nan  # ATR(14) of TF at the arming bar (stops in ATR units, spec section 4)
    level1_moves: int = 0  # how many times level 1 moved up after the break bar ("the high kept updating", analysed only)
    confluence: tuple[ConfluenceZone, ...] = field(default_factory=tuple)

    def fib(self, ratio: float) -> float:
        return self.level0 + self.side * ratio * abs(self.level1 - self.level0)

    @property
    def confluence_score(self) -> int:
        return len({z.kind for z in self.confluence})


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    return ind.atr(high, low, close, ATR_PERIOD, ATR_PERIOD)


def swing_highs(high: np.ndarray, k: int = SWING_K) -> np.ndarray:
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


def swing_lows(low: np.ndarray, k: int = SWING_K) -> np.ndarray:
    return swing_highs(-low, k)


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
    anchors = range(len(recent) - 1)
    if p.line_from_major_high:
        recent = known[int(np.argmax(high[known])) :]  # the major high, then every later swing as a second point
        anchors = range(min(1, len(recent) - 1))
    best: tuple[int, int, Line, list[int]] | None = None
    for ia in anchors:
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
            if p.max_wick_pierce_atr is not None and np.any(high[a:t] > line.at(seg) + p.max_wick_pierce_atr * np.nan_to_num(a_tr[a:t], nan=np.inf)):
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
    for sw in swing_highs(h[: t + 1]):
        if sw + SWING_K <= t and sw < s.level0_index and overlaps(h[sw], h[sw]):
            levels.append(ConfluenceZone("level", float(h[sw]), float(h[sw]), int(sw)))
    for sw in swing_lows(lo[: t + 1]):
        if sw + SWING_K <= t and sw < s.level0_index and overlaps(lo[sw], lo[sw]):
            levels.append(ConfluenceZone("level", float(lo[sw]), float(lo[sw]), int(sw)))
    # keep the most recent few prior swing levels only (older chop would otherwise flood the list)
    out.extend(sorted(levels, key=lambda z: -z.index)[: p.max_level_zones])
    return tuple(out)


def zone_broken_by_impulse(t: int, o: np.ndarray, lo: np.ndarray, c: np.ndarray, v: np.ndarray | None, a_tr: np.ndarray, zone_low: float, p: S7Params) -> bool:
    """Owner's rule: bar ``t`` went through the whole entry zone (its low below the zone, wherever it closed) with a big
    bearish body or big volume (vs the median of the previous ``volume_median_bars`` bars - bar ``t`` itself is not
    part of its own yardstick)."""
    if lo[t] >= zone_low:
        return False
    if o[t] - c[t] >= p.zone_break_body_atr * a_tr[t]:
        return True
    if v is None or t < 1:
        return False
    past = v[max(0, t - p.volume_median_bars) : t]
    past = past[np.isfinite(past)]
    return bool(past.size) and math.isfinite(v[t]) and v[t] >= p.zone_break_volume_mult * float(np.median(past))


def _detect_long(o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, p: S7Params, start: int = 0, v: np.ndarray | None = None) -> list[S7Setup]:
    n = len(c)
    a_tr = atr(h, lo, c)
    swings = swing_highs(h)
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
            crossed = c[t] > float(line.at(t)) + p.touch_tol_atr * a_tr[t]
            if not crossed and p.max_wick_pierce_atr is not None and h[t] > float(line.at(t)) + p.max_wick_pierce_atr * a_tr[t]:
                line = None  # a wick through the line without a close above it makes the line crooked
                continue
            if crossed:
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
            fvg_ok = not p.impulse_fvg or (t >= 2 and lo[t] > h[t - 2])
            if p.break_on_cross:  # variant 12: any close beyond the line breaks it; only the variant-3 impulse rules apply
                above_line = c[t] > float(pending["line"].at(t)) + p.touch_tol_atr * a_tr[t]
                broke = above_line and fvg_ok and (p.impulse_body_atr is None or body >= p.impulse_body_atr * a_tr[t])
            else:
                body_need = p.range_impulse_body_atr if pending["range"] is not None else p.impulse_body_atr
                broke = c[t] >= pending["required"] and fvg_ok and (body_need is None or body >= body_need * a_tr[t])
            if broke:
                last = pending["last"]
                rng = pending["range"]
                l0_idx = last + int(np.argmin(lo[last : t + 1]))
                level0 = float(lo[l0_idx])
                if p.level0_range_bottom and rng is not None:
                    level0, l0_idx = rng.bottom, rng.start + int(np.argmin(lo[rng.start : rng.end + 1]))
                leg = {"break": t, "l0_idx": l0_idx, "level0": level0, "l1_idx": t, "level1": float(c[t]), "moves": 0, "armed_l1": None}
                phase = "leg"
            continue
        if phase == "leg":
            if c[t] > leg["level1"]:
                leg["level1"], leg["l1_idx"] = float(c[t]), t
                leg["moves"] += 1
            if c[t] < leg["level0"] or t - leg["break"] > p.max_leg_bars:
                phase, line, search_from = "seek", None, t
                continue
            if leg["armed_l1"] is not None:
                if leg["armed_l1"] == leg["l1_idx"]:  # armed and level 1 unchanged: wait for a new high or the expiry
                    if t > leg["armed_until"]:
                        phase, line, search_from = "seek", None, leg["break"]
                    continue
                leg["armed_l1"] = None  # a close above level 1: it moved, the setup may re-arm (spec section 3)
            span = leg["level1"] - leg["level0"]
            if t > leg["l1_idx"] and span > 0 and lo[t] <= leg["level1"] - p.freeze_pullback * span:
                if span < p.min_leg_atr * a_tr[t]:
                    phase, line, search_from = "seek", None, leg["break"]  # a wiggle, not an impulse leg
                    continue
                far, near = (0.5, 0.382) if p.shallow_zone else (0.618, 0.5)  # retracement back from level 1
                zone_low, zone_high = leg["level1"] - far * span, leg["level1"] - near * span
                beyond = float(np.max(h[leg["break"] : t + 1])) > pending["line"].a_price
                if (beyond and p.skip_beyond_line_start) or zone_broken_by_impulse(t, o, lo, c, v, a_tr, zone_low, p):
                    phase, line, search_from = "seek", None, leg["break"]
                    continue
                setup = S7Setup(
                    side=1, line=pending["line"], touches=pending["touches"], last_touch=pending["last"], h_last=pending["h_last"],
                    range_box=pending["range"], cross_index=pending["cross"], break_index=leg["break"], level0_index=leg["l0_idx"],
                    level0=leg["level0"], level1_index=leg["l1_idx"], level1=leg["level1"], arm_index=t,
                    zone_low=zone_low, zone_high=zone_high, beyond_line_start=beyond,
                    zone_touched_at_arm=bool(lo[t] <= zone_high + p.touch_tol_atr * a_tr[t]), atr=float(a_tr[t]),
                    limit_618=zone_high if p.shallow_zone else zone_low,
                    level1_moves=leg["moves"],
                )
                out.append(replace(setup, confluence=_confluence(setup, t, o, h, lo, c, a_tr, p)))
                leg["armed_l1"], leg["armed_until"] = leg["l1_idx"], t + p.cancel_after_mult * (t - leg["break"])
    return out


def _mirror_setup(s: S7Setup) -> S7Setup:
    neg = lambda z: ConfluenceZone(z.kind, -z.high, -z.low, z.index)  # noqa: E731
    return replace(
        s, side=-1, line=Line(s.line.a_index, -s.line.a_price, -s.line.slope), h_last=-s.h_last,
        range_box=None if s.range_box is None else RangeBox(s.range_box.start, s.range_box.end, -s.range_box.bottom, -s.range_box.top),
        level0=-s.level0, level1=-s.level1, zone_low=-s.zone_high, zone_high=-s.zone_low, limit_618=-s.limit_618,
        confluence=tuple(neg(z) for z in s.confluence),
    )


def detect_setups(o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, params: S7Params | None = None, start: int = 0, volume: np.ndarray | None = None) -> list[S7Setup]:
    """All armed long and short setups, in arming order. Shorts: the long detector on the reflected series (volume is
    not reflected). Without ``volume`` the zone-break rule uses the body condition only."""
    p = params or S7Params()
    o, h, lo, c = (np.asarray(x, dtype=float) for x in (o, h, lo, c))
    v = None if volume is None else np.asarray(volume, dtype=float)
    longs = _detect_long(o, h, lo, c, p, start, v)
    shorts = [_mirror_setup(s) for s in _detect_long(-o, -lo, -h, -c, p, start, v)]
    return sorted(longs + shorts, key=lambda s: (s.arm_index, s.side))
