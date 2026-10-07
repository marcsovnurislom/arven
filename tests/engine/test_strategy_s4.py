"""Phase 7 gate: hand-computed tests for strategy S4's swing/impulse/zone/trendline/trigger/target math
(`docs/strategy_impulse_retest.md`)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from arven.engine.strategy_s4 import (
    Impulse,
    Swing,
    SwingKind,
    TargetLevel,
    TrendLine,
    Zone,
    build_decision,
    confirmed_swings,
    confluence_zone,
    counter_trend_trendline,
    find_last_impulse,
    find_trigger,
)

NAN = math.nan


# --- confirmed_swings ----------------------------------------------------------------------------------


def test_confirmed_swings_finds_a_clean_high_and_low():
    high = np.array([1.0, 2.0, 5.0, 2.0, 1.0, 1.0, 1.0, 6.0, 1.0, 1.0])
    low = np.array([1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    swings = confirmed_swings(high, low, k=2)
    kinds_at = {(s.index, s.kind): s.confirmed_at for s in swings}
    assert kinds_at[(2, SwingKind.HIGH)] == 4
    assert kinds_at[(4, SwingKind.LOW)] == 6
    assert kinds_at[(7, SwingKind.HIGH)] == 9


def test_confirmed_swings_requires_strict_inequality_on_both_sides():
    # a plateau (equal values) is never a swing - strict > / < on every neighbour.
    high = np.array([1.0, 3.0, 3.0, 3.0, 1.0])
    low = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    assert confirmed_swings(high, low, k=1) == ()


def test_confirmed_swings_rejects_k_below_one():
    with pytest.raises(ValueError):
        confirmed_swings(np.array([1.0]), np.array([1.0]), k=0)


def test_confirmed_swings_truncation_leakage():
    """CLAUDE.md: every causal computation needs a truncation test. A swing confirmed within a truncated
    prefix of the array must report exactly the same (index, kind, price, confirmed_at) as computing it on
    the full array - truncating the array further out must never change an already-confirmed swing."""
    rng = np.random.default_rng(3)
    high = rng.uniform(90, 110, 60)
    low = high - rng.uniform(1, 5, 60)
    full = confirmed_swings(high, low, k=2)
    for cutoff in (10, 20, 35, 50):
        truncated = confirmed_swings(high[:cutoff], low[:cutoff], k=2)
        expected = tuple(s for s in full if s.confirmed_at < cutoff)
        assert truncated == expected, f"cutoff={cutoff}"


def test_confirmed_swings_ignores_bars_adjacent_to_nan():
    high = np.array([1.0, 2.0, NAN, 2.0, 1.0])
    low = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    # index 1 would be a swing high at k=1 but its right neighbour is NaN -> comparison is false -> no swing.
    assert confirmed_swings(high, low, k=1) == ()


# --- find_last_impulse ---------------------------------------------------------------------------------


def _atr_const(n: int, value: float, nan_before: int = 0) -> np.ndarray:
    a = np.full(n, value)
    a[:nan_before] = NAN
    return a


def test_find_last_impulse_qualifies_when_size_is_at_least_3x_atr():
    swings = (Swing(0, SwingKind.LOW, 100.0, 2), Swing(5, SwingKind.HIGH, 110.0, 7))
    atr = _atr_const(10, 3.0)  # 3x ATR = 9 <= size 10
    impulse = find_last_impulse(swings, atr, as_of_index=7)
    assert impulse == Impulse(swings[0], swings[1], 1, 10.0)


def test_find_last_impulse_is_none_before_the_end_swing_is_confirmed():
    swings = (Swing(0, SwingKind.LOW, 100.0, 2), Swing(5, SwingKind.HIGH, 110.0, 7))
    atr = _atr_const(10, 3.0)
    assert find_last_impulse(swings, atr, as_of_index=6) is None  # confirmed_at=7 not yet reached
    assert find_last_impulse(swings, atr, as_of_index=7) is not None  # reached exactly


def test_find_last_impulse_rejects_a_leg_smaller_than_the_threshold():
    swings = (Swing(0, SwingKind.LOW, 100.0, 2), Swing(5, SwingKind.HIGH, 108.0, 7))  # size 8 < 3*3=9
    atr = _atr_const(10, 3.0)
    assert find_last_impulse(swings, atr, as_of_index=7) is None


def test_find_last_impulse_skips_same_kind_adjacent_swings_and_finds_an_older_qualifying_leg():
    swings = (
        Swing(0, SwingKind.LOW, 100.0, 2),
        Swing(5, SwingKind.HIGH, 110.0, 7),   # qualifying leg (size 10 >= 9)
        Swing(6, SwingKind.HIGH, 111.0, 8),   # same kind as the previous - skipped, not a leg
    )
    atr = _atr_const(10, 3.0)
    impulse = find_last_impulse(swings, atr, as_of_index=8)
    assert impulse == Impulse(swings[0], swings[1], 1, 10.0)


def test_find_last_impulse_bearish_direction():
    swings = (Swing(0, SwingKind.HIGH, 110.0, 2), Swing(5, SwingKind.LOW, 100.0, 7))
    atr = _atr_const(10, 3.0)
    impulse = find_last_impulse(swings, atr, as_of_index=7)
    assert impulse.side == -1 and impulse.size == 10.0


def test_find_last_impulse_none_when_no_swings_at_all():
    assert find_last_impulse((), _atr_const(5, 1.0), as_of_index=4) is None


# --- confluence_zone ------------------------------------------------------------------------------------


def _impulse_bull(start_index=5, start_price=100.0, end_index=10, end_price=110.0):
    return Impulse(Swing(start_index, SwingKind.LOW, start_price, start_index + 2), Swing(end_index, SwingKind.HIGH, end_price, end_index + 2), 1, end_price - start_price)


def test_confluence_zone_full_overlap_when_base_candle_contains_the_fib_band():
    impulse = _impulse_bull()  # fib band = [110 - 6.18, 110 - 5.0] = [103.82, 105.0]
    high = np.zeros(10)
    low = np.zeros(10)
    high[4], low[4] = 106.0, 102.0  # base candle at start.index - 1 = 4; range 4
    atr = _atr_const(10, 1.0)  # need range >= 1.0*1.0 -> 4 >= 1 OK
    zone = confluence_zone(impulse, high, low, atr)
    assert zone == Zone(pytest.approx(103.82), pytest.approx(105.0), pytest.approx(103.82), pytest.approx(105.0))
    assert zone.overlap_fraction == pytest.approx(1.0)


def test_confluence_zone_partial_overlap_fraction():
    impulse = _impulse_bull()
    high = np.zeros(10)
    low = np.zeros(10)
    high[4], low[4] = 110.0, 104.0  # base = [104, 110]; fib band [103.82, 105.0] -> intersection [104, 105.0]
    atr = _atr_const(10, 1.0)
    zone = confluence_zone(impulse, high, low, atr)
    assert zone.lower == pytest.approx(104.0) and zone.upper == pytest.approx(105.0)
    assert zone.overlap_fraction == pytest.approx((105.0 - 104.0) / (105.0 - 103.82))


def test_confluence_zone_none_when_base_candle_too_small():
    impulse = _impulse_bull()
    high, low = np.zeros(10), np.zeros(10)
    high[4], low[4] = 102.5, 102.0  # range 0.5
    atr = _atr_const(10, 1.0)  # need >= 1.0 -> 0.5 fails
    assert confluence_zone(impulse, high, low, atr) is None


def test_confluence_zone_none_when_bands_do_not_overlap():
    impulse = _impulse_bull()
    high, low = np.zeros(10), np.zeros(10)
    high[4], low[4] = 50.0, 10.0  # huge base candle, but nowhere near the fib band [103.82, 105.0]... wait overlaps by construction since base must qualify but be disjoint
    atr = _atr_const(10, 1.0)
    assert confluence_zone(impulse, high, low, atr) is None


def test_confluence_zone_none_when_start_is_the_first_bar():
    impulse = _impulse_bull(start_index=0)
    high, low = np.zeros(5), np.zeros(5)
    assert confluence_zone(impulse, high, low, _atr_const(5, 1.0)) is None


# --- counter_trend_trendline ----------------------------------------------------------------------------


def test_counter_trend_trendline_uses_the_last_two_confirmed_counter_trend_pivots():
    impulse = _impulse_bull(end_index=5)
    swings = (
        Swing(8, SwingKind.HIGH, 108.0, 10),
        Swing(12, SwingKind.HIGH, 106.0, 14),
        Swing(15, SwingKind.LOW, 104.0, 17),  # wrong kind (counter-trend for a bullish impulse is HIGH)
    )
    line = counter_trend_trendline(swings, impulse, as_of_index=14)
    assert line == TrendLine(8, 108.0, 12, 106.0)
    assert line.price_at(8) == 108.0 and line.price_at(12) == 106.0
    assert line.price_at(10) == pytest.approx(107.0)  # linear midpoint


def test_counter_trend_trendline_none_before_the_second_pivot_is_confirmed():
    impulse = _impulse_bull(end_index=5)
    swings = (Swing(8, SwingKind.HIGH, 108.0, 10), Swing(12, SwingKind.HIGH, 106.0, 14))
    assert counter_trend_trendline(swings, impulse, as_of_index=13) is None  # second pivot confirms at 14
    assert counter_trend_trendline(swings, impulse, as_of_index=14) is not None


def test_counter_trend_trendline_ignores_pivots_before_the_impulse_end():
    impulse = _impulse_bull(end_index=10)
    swings = (Swing(3, SwingKind.HIGH, 101.0, 5), Swing(4, SwingKind.HIGH, 102.0, 6))  # both before end_index=10
    assert counter_trend_trendline(swings, impulse, as_of_index=20) is None


# --- find_trigger ---------------------------------------------------------------------------------------


def test_find_trigger_fires_on_the_first_bar_that_breaks_then_holds_a_retest():
    line = TrendLine(8, 108.0, 12, 106.0)  # price_at(t) = 108 - 0.5*(t-8)
    zone = Zone(103.0, 104.5, 103.0, 104.5)
    close = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 107.0, 108.0, 105.0, 103.5])  # index 12..15
    high = close.copy()
    low = close.copy()
    low[14] = 103.8  # index 14: price_at(14) = 108 - 0.5*6 = 105.0; close[14]=105 (not > line, broke stays from 12/13)
    # break already true from index 12 (close 107 > price_at(12)=106); retest+hold check at 14: low<=104.5 and close>=103.0
    idx = find_trigger(close, high, low, line, zone, side=1, search_from_index=12)
    assert idx == 14


def test_find_trigger_never_fires_without_a_prior_break():
    line = TrendLine(0, 100.0, 1, 100.0)  # flat line at 100
    zone = Zone(90.0, 95.0, 90.0, 95.0)
    close = np.array([80.0, 92.0, 80.0])  # never closes above 100, so never "broke"
    low = np.array([80.0, 92.0, 80.0])
    idx = find_trigger(close, close, low, line, zone, side=1, search_from_index=0)
    assert idx is None


def test_find_trigger_short_side_mirrors_long():
    line = TrendLine(0, 100.0, 1, 100.0)
    zone = Zone(95.0, 97.0, 95.0, 97.0)
    close = np.array([99.0, 96.0])  # bar0 closes below line (break for a short); bar1 holds inside/above zone low
    high = np.array([99.0, 96.5])
    low = np.array([99.0, 96.0])
    idx = find_trigger(close, high, low, line, zone, side=-1, search_from_index=0)
    assert idx == 1


def test_find_trigger_returns_none_when_never_touched_within_the_given_data():
    line = TrendLine(0, 100.0, 1, 100.0)
    zone = Zone(90.0, 95.0, 90.0, 95.0)
    close = np.array([101.0, 102.0, 103.0])  # broke, but low never comes back down to the zone
    low = np.array([101.0, 102.0, 103.0])
    assert find_trigger(close, close, low, line, zone, side=1, search_from_index=0) is None


# --- build_decision -------------------------------------------------------------------------------------


def test_build_decision_stop_and_targets_match_the_spec_formulas_by_hand():
    impulse = Impulse(Swing(0, SwingKind.LOW, 94.0, 2), Swing(5, SwingKind.HIGH, 104.0, 7), 1, 10.0)
    zone = Zone(100.0, 102.0, 100.0, 102.0)  # full overlap -> confidence 1.0
    decision = build_decision(impulse, zone, entry_price=104.0, atr_at_entry=4.0, trigger_index=20)
    assert decision.stop == pytest.approx(99.0)  # 100.0 - 0.25*4.0
    assert decision.confidence == pytest.approx(1.0)
    assert decision.targets == (
        TargetLevel(1.0, pytest.approx(114.0), pytest.approx(2.0), 0.5),
        TargetLevel(1.414, pytest.approx(118.14), pytest.approx(2.828), 0.3),
        TargetLevel(1.618, pytest.approx(120.18), pytest.approx(3.236), 0.2),
    )


def test_build_decision_short_side_mirrors_long():
    impulse = Impulse(Swing(0, SwingKind.HIGH, 110.0, 2), Swing(5, SwingKind.LOW, 100.0, 7), -1, 10.0)
    zone = Zone(102.0, 104.0, 102.0, 104.0)
    decision = build_decision(impulse, zone, entry_price=102.0, atr_at_entry=4.0, trigger_index=20)
    assert decision.stop == pytest.approx(105.0)  # 104.0 + 0.25*4.0
    assert decision.targets[0].price == pytest.approx(102.0 - 1.0 * 10.0)
    assert decision.targets[0].r_multiple == pytest.approx(10.0 / 3.0)  # risk = |102-105| = 3.0


def test_build_decision_confidence_is_clamped_to_a_minimum_of_0_1():
    impulse = Impulse(Swing(0, SwingKind.LOW, 94.0, 2), Swing(5, SwingKind.HIGH, 104.0, 7), 1, 10.0)
    zone = Zone(100.0, 100.01, 100.0, 102.0)  # overlap_fraction ~ 0.005, below the floor
    decision = build_decision(impulse, zone, entry_price=104.0, atr_at_entry=4.0, trigger_index=20)
    assert decision.confidence == pytest.approx(0.1)


def test_close_fractions_sum_to_one_matching_the_spec():
    from arven.engine.strategy_s4 import CLOSE_FRACTIONS

    assert sum(CLOSE_FRACTIONS) == pytest.approx(1.0)
