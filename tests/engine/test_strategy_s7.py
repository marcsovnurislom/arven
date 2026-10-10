"""S7 detector (docs/strategy_s7_trend_break_fib.md section 2) on hand-built price paths."""

from __future__ import annotations

import numpy as np
import pytest

from arven.engine.strategy_s7 import S7Params, detect_setups


def path(points: list[tuple[int, float]], n: int, wick: float = 0.3):
    """Closes linearly interpolated through (index, price) waypoints; open halfway from the previous close (so a peak
    bar's high is strictly above its neighbours'); wicks of +-wick."""
    idx, val = zip(*points, strict=True)
    c = np.interp(np.arange(n), idx, val)
    o = (np.concatenate([[c[0]], c[:-1]]) + c) / 2
    h = np.maximum(o, c) + wick
    lo = np.minimum(o, c) - wick
    return o, h, lo, c


# A descending line through highs at bars 20, 50, 80 (110.3, 107.3, 104.3), deep dips between the touches, a low at
# bar 95, an impulsive break at bar 105 that closes above the last touch high, a rally to 108 and a pullback.
LONG = [(0, 104), (20, 110), (35, 104), (50, 107), (65, 101), (80, 104), (95, 96), (104, 100), (105, 105), (110, 108), (116, 104), (140, 103)]


def test_long_setup_geometry_hand_checked():
    o, h, lo, c = path(LONG, 140)
    setups = detect_setups(o, h, lo, c)
    longs = [s for s in setups if s.side == 1]
    assert len(longs) == 1
    s = longs[0]
    assert s.touches == (20, 50, 80) and s.last_touch == 80 and s.h_last == pytest.approx(104.3)
    assert s.break_index == 105 and s.cross_index == 105 and s.range_box is None
    assert s.level0_index == 95 and s.level0 == pytest.approx(95.7)
    assert s.level1_index == 110 and s.level1 == pytest.approx(108.0)
    span = 108.0 - 95.7
    assert s.arm_index == 114  # first bar whose low is 0.236 of the leg below the highest close
    assert s.zone_low == pytest.approx(108.0 - 0.618 * span) and s.zone_high == pytest.approx(108.0 - 0.5 * span)
    assert s.fib(1.618) == pytest.approx(95.7 + 1.618 * span)


def test_setup_is_causal_truncating_after_the_arming_bar_changes_nothing():
    o, h, lo, c = path(LONG, 140)
    full = [s for s in detect_setups(o, h, lo, c) if s.side == 1][0]
    cut = [s for s in detect_setups(o[:115], h[:115], lo[:115], c[:115]) if s.side == 1]
    assert len(cut) == 1 and cut[0] == full
    assert [s for s in detect_setups(o[:114], h[:114], lo[:114], c[:114]) if s.side == 1] == []


def test_short_is_the_exact_mirror():
    o, h, lo, c = path(LONG, 140)
    mirrored = detect_setups(-o, -lo, -h, -c)
    shorts = [s for s in mirrored if s.side == -1]
    long_ = [s for s in detect_setups(o, h, lo, c) if s.side == 1][0]
    assert len(shorts) == 1
    s = shorts[0]
    assert (s.break_index, s.arm_index, s.touches) == (long_.break_index, long_.arm_index, long_.touches)
    assert s.level0 == pytest.approx(-long_.level0) and s.level1 == pytest.approx(-long_.level1)
    assert s.zone_low == pytest.approx(-long_.zone_high) and s.fib(1.0) == pytest.approx(s.level1)


def test_two_touches_are_not_enough_by_default_but_are_with_the_variant():
    pts = [(0, 104), (20, 110), (35, 104), (50, 107), (95, 96), (104, 100), (105, 108), (110, 110), (116, 105), (140, 104)]
    o, h, lo, c = path(pts, 140)
    assert [s for s in detect_setups(o, h, lo, c) if s.side == 1] == []
    two = [s for s in detect_setups(o, h, lo, c, S7Params(min_touches=2)) if s.side == 1]
    assert len(two) == 1 and two[0].touches == (20, 50)


def test_break_must_close_at_or_above_the_last_touch_high():
    # bar 105 crosses the line but closes below 104.3; the break completes only at bar 107, the first close above it
    pts = [(0, 104), (20, 110), (35, 104), (50, 107), (65, 101), (80, 104), (95, 96), (104, 100), (105, 103), (106, 103.5), (107, 106), (110, 108), (116, 104), (140, 103)]
    o, h, lo, c = path(pts, 140)
    s = [x for x in detect_setups(o, h, lo, c) if x.side == 1][0]
    assert s.cross_index == 105 and s.break_index == 107


def _range_path():
    """Touches at 20/50/80, then a tight sideways range (bars 82-104) that the descending line drifts into, so a close
    crosses the line inside the range; the range top is cleared only later, by an impulsive bar."""
    pts = [(0, 104), (20, 110), (35, 104), (50, 107), (65, 101), (80, 104), (82, 102.0)]
    n = 140
    c = np.interp(np.arange(n), *zip(*pts, strict=True))
    for i in range(82, 105):
        c[i] = 102.0 if i % 2 == 0 else 102.6
    c[105], c[106], c[107] = 102.9, 104.5, 107.0  # 106: closes above everything but with a small body; 107: impulse
    for i in range(108, n):
        c[i] = 107.0 + (i - 107) * 0.5 if i <= 112 else 109.5 - (i - 112) * 0.6
    o = (np.concatenate([[c[0]], c[:-1]]) + c) / 2
    o[106], o[107] = 104.2, 104.5
    h = np.maximum(o, c) + 0.2
    lo = np.minimum(o, c) - 0.2
    return o, h, lo, c


def test_range_break_needs_the_range_top_and_an_impulse_possibly_on_a_later_bar():
    o, h, lo, c = _range_path()
    s = [x for x in detect_setups(o, h, lo, c) if x.side == 1][0]
    assert s.range_box is not None
    # the band also takes in the last bars of the drift into the range (they fit in 3 ATR), so its top is their high
    assert s.range_box.bottom == pytest.approx(101.8) and 102.8 <= s.range_box.top < 104.5
    assert s.cross_index < s.break_index  # crossed the line by drift first, broke out later
    assert s.break_index == 107  # bar 106 cleared the range but with a small body; 107 is the impulse


def test_close_below_the_range_bottom_cancels_the_pending_break():
    o, h, lo, c = _range_path()
    c = c.copy()
    c[106] = 101.0  # breaks down out of the range before any breakout
    o = (np.concatenate([[c[0]], c[:-1]]) + c) / 2
    o[107] = 104.5
    h = np.maximum(o, c) + 0.2
    lo = np.minimum(o, c) - 0.2
    longs = [x for x in detect_setups(o, h, lo, c) if x.side == 1]
    assert all(x.break_index != 107 for x in longs)
