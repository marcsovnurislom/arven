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


# --- round-1 rules from the owner's check of 100 development setups (spec section 8) ---


def test_a_wick_far_through_the_line_makes_it_crooked():
    o, h, lo, c = path(LONG, 140)
    h = h.copy()
    h[60] = 108.5  # a spike ~2 ATR through the line (106.3 at bar 60) that closes back below it
    assert all(s.touches != (20, 50, 80) for s in detect_setups(o, h, lo, c) if s.side == 1)
    loose = [s for s in detect_setups(o, h, lo, c, S7Params(max_wick_pierce_atr=None)) if s.side == 1]
    assert [s.touches for s in loose] == [(20, 50, 80)]


def test_leg_above_the_lines_first_anchor_is_skipped_by_default_and_flagged_with_the_variant():
    pts = [(0, 104), (20, 110), (35, 104), (50, 107), (65, 101), (80, 104), (95, 96), (104, 100), (105, 105), (110, 112), (116, 106), (140, 105)]
    o, h, lo, c = path(pts, 140)
    assert [s for s in detect_setups(o, h, lo, c) if s.side == 1] == []
    kept = [s for s in detect_setups(o, h, lo, c, S7Params(skip_beyond_line_start=False)) if s.side == 1]
    assert len(kept) == 1 and kept[0].beyond_line_start
    assert not [s for s in detect_setups(*path(LONG, 140)) if s.side == 1][0].beyond_line_start


def _zone_break_path(body_big: bool):
    """LONG, but the arming bar 112 drops from 108 to a close below the entry zone (100.4-101.85)."""
    o, h, lo, c = path(LONG[:-2] + [(111, 108), (130, 103), (140, 103)], 140)
    o, h, lo, c = o.copy(), h.copy(), lo.copy(), c.copy()
    c[112] = 100.2
    o[112] = 104.1 if body_big else 100.8  # small body: a gap down, then a quiet bar
    h[112], lo[112] = max(o[112], c[112]) + 0.3, min(o[112], c[112]) - 0.3
    return o, h, lo, c


def test_an_impulse_closing_through_the_whole_zone_cancels_the_setup():
    o, h, lo, c = _zone_break_path(body_big=True)
    assert [s for s in detect_setups(o, h, lo, c) if s.side == 1 and s.break_index == 105] == []
    off = S7Params(zone_break_body_atr=1e9)
    assert [s.arm_index for s in detect_setups(o, h, lo, c, off) if s.side == 1 and s.break_index == 105] == [112]


def test_big_volume_on_a_small_bodied_zone_break_also_cancels_it():
    o, h, lo, c = _zone_break_path(body_big=False)
    vol = np.ones(140)
    armed = [s for s in detect_setups(o, h, lo, c, volume=vol) if s.side == 1 and s.break_index == 105]
    assert len(armed) == 1 and armed[0].arm_index == 112 and armed[0].zone_touched_at_arm
    vol[112] = 2.0  # twice the median of the previous 20 bars
    assert [s for s in detect_setups(o, h, lo, c, volume=vol) if s.side == 1 and s.break_index == 105] == []
    assert [s for s in detect_setups(o[:112], h[:112], lo[:112], c[:112], volume=vol[:112]) if s.side == 1] == []


def test_a_big_bar_whose_wick_runs_through_the_zone_cancels_it_even_if_it_closes_back_inside():
    o, h, lo, c = _zone_break_path(body_big=True)
    c[112], lo[112] = 101.0, 99.0  # body 104.1 -> 101.0 (inside the zone), wick down to 99.0 (below it)
    assert [s for s in detect_setups(o, h, lo, c) if s.side == 1 and s.break_index == 105] == []
    lo[112] = 100.7  # the wick stays inside the zone: armed, and the zone counts as touched
    armed = [s for s in detect_setups(o, h, lo, c) if s.side == 1 and s.break_index == 105]
    assert len(armed) == 1 and armed[0].zone_touched_at_arm


# --- round-2 variants (owner's choice: let the data decide) ---


def test_variant_12_the_first_close_beyond_the_line_is_the_break():
    pts = [(0, 104), (20, 110), (35, 104), (50, 107), (65, 101), (80, 104), (95, 96), (104, 100), (105, 103), (106, 103.5), (107, 106), (110, 108), (116, 104), (140, 103)]
    o, h, lo, c = path(pts, 140)
    s = [x for x in detect_setups(o, h, lo, c, S7Params(break_on_cross=True)) if x.side == 1][0]
    assert s.cross_index == 105 and s.break_index == 105  # baseline: 107 (see the last-touch-high test)


def test_variant_13_the_line_must_start_at_the_major_high():
    o, h, lo, c = path(LONG, 140)
    base = [s for s in detect_setups(o, h, lo, c) if s.side == 1]
    assert [s for s in detect_setups(o, h, lo, c, S7Params(line_from_major_high=True)) if s.side == 1] == base  # bar 20 is the major high
    # an earlier, higher peak at bar 8 becomes the major high; no line from it has 3 touches, so the variant finds nothing
    o2, h2, lo2, c2 = path([(0, 104), (8, 116), (14, 104)] + LONG[1:], 140)
    assert [s.touches for s in detect_setups(o2, h2, lo2, c2) if s.side == 1] == [(20, 50, 80)]
    assert [s for s in detect_setups(o2, h2, lo2, c2, S7Params(line_from_major_high=True)) if s.side == 1] == []


# --- evaluation-stage additions: re-arming, variant 3 (FVG), variant 14 (zone convention), recorded fields ---


def test_a_close_above_level1_re_arms_the_same_leg_with_the_new_level1():
    pts = LONG[:-2] + [(116, 104), (122, 109.5), (128, 106), (140, 105.5)]
    o, h, lo, c = path(pts, 140)
    longs = [s for s in detect_setups(o, h, lo, c) if s.side == 1]
    assert [s.break_index for s in longs] == [105, 105]
    first, second = longs
    assert first.level1 == pytest.approx(108.0) and first.arm_index == 114
    assert second.level1 == pytest.approx(109.5) and second.level1_index == 122 and second.arm_index > 122
    assert second.level0 == first.level0 and second.level1_moves > first.level1_moves


def test_variant_3_fvg_the_break_bar_must_leave_a_gap():
    o, h, lo, c = path(LONG, 140)
    lo = lo.copy()
    lo[105] = h[103] - 0.1  # bar 105 still closes above the line and the last touch high, but leaves no 3-candle gap
    assert [s.break_index for s in detect_setups(o, h, lo, c) if s.side == 1] == [105]
    fvg = [s for s in detect_setups(o, h, lo, c, S7Params(impulse_fvg=True)) if s.side == 1]
    assert [s.break_index for s in fvg] == [106] and lo[106] > h[104]


def test_variant_14_shallow_zone_and_the_recorded_fields():
    o, h, lo, c = path(LONG, 140)
    deep = [s for s in detect_setups(o, h, lo, c) if s.side == 1][0]
    shallow = [s for s in detect_setups(o, h, lo, c, S7Params(shallow_zone=True)) if s.side == 1][0]
    span = 108.0 - 95.7
    assert deep.limit_618 == pytest.approx(108.0 - 0.618 * span) == pytest.approx(deep.zone_low)
    assert shallow.zone_low == pytest.approx(108.0 - 0.5 * span) and shallow.zone_high == pytest.approx(108.0 - 0.382 * span)
    assert shallow.limit_618 == pytest.approx(shallow.zone_high) == pytest.approx(shallow.fib(0.618))
    assert deep.fib(0.5) == pytest.approx(shallow.fib(0.5))  # fib 0.5 is the same price in both conventions
    assert np.isfinite(deep.atr) and deep.atr > 0
    short = [s for s in detect_setups(-o, -lo, -h, -c) if s.side == -1][0]
    assert short.limit_618 == pytest.approx(-deep.limit_618) and short.atr == pytest.approx(deep.atr)
