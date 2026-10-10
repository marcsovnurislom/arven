"""S7 trade plan (docs/strategy_s7_trend_break_fib.md sections 3-5): hand-computed levels."""

from __future__ import annotations

import numpy as np
import pytest

from arven.engine.strategy_s7 import Line, S7Params, S7Setup
from arven.engine.strategy_s7_plan import (
    S7TradeParams,
    e1_trigger,
    ladder_r,
    limit_orders,
    orient,
    s3_exit_index,
    stop_price,
    targets,
    tf_cancel_reason,
)


def long_setup(**kw) -> S7Setup:
    """Level 0 = 90, level 1 = 110 (span 20), deep zone 97.64-100, ATR 2."""
    base = dict(
        side=1, line=Line(0, 120.0, -0.1), touches=(1, 2, 3), last_touch=3, h_last=110.0, range_box=None, cross_index=8,
        break_index=8, level0_index=7, level0=90.0, level1_index=9, level1=110.0, arm_index=10, zone_low=97.64, zone_high=100.0,
        limit_618=97.64, atr=2.0,
    )
    base.update(kw)
    return S7Setup(**base)


def short_setup() -> S7Setup:
    """The long setup reflected through 200: level 0 = 110, level 1 = 90, zone 100-102.36."""
    return long_setup(side=-1, h_last=90.0, level0=110.0, level1=90.0, zone_low=100.0, zone_high=102.36, limit_618=102.36)


def test_stops():
    s = long_setup()
    assert stop_price(s, S7TradeParams(stop="S1")) == pytest.approx(92.0)  # fib 0.1 = 90 + 0.1 * 20
    assert stop_price(s, S7TradeParams(stop="S2")) == pytest.approx(89.5)  # 90 - 0.25 * 2
    assert stop_price(s, S7TradeParams(stop="S3")) == pytest.approx(88.0)  # 90 - 1 * 2 (hard stop)
    assert stop_price(short_setup(), S7TradeParams(stop="S2")) == pytest.approx(110.5)


def test_limit_orders_nearest_first_in_both_zone_conventions():
    s = long_setup()
    assert limit_orders(s, S7TradeParams(entry="E1")) == ()
    assert limit_orders(s, S7TradeParams(entry="E2")) == ((97.64, 1.0),)
    assert limit_orders(s, S7TradeParams(entry="E3")) == ((100.0, 1.0),)
    assert limit_orders(s, S7TradeParams(entry="E4")) == ((100.0, 0.5), (97.64, 0.5))
    shallow = long_setup(zone_low=100.0, zone_high=102.36, limit_618=102.36)  # variant 14: 0.618 counted from level 0
    assert limit_orders(shallow, S7TradeParams(entry="E4")) == ((102.36, 0.5), (100.0, 0.5))
    assert limit_orders(short_setup(), S7TradeParams(entry="E4")) == ((100.0, 0.5), (102.36, 0.5))


def test_targets_use_the_nearest_resistance_inside_the_band():
    s = long_setup()
    plain = targets(s, S7TradeParams(), np.array([]))
    assert [p for p, _ in plain] == pytest.approx([110.0, 122.36, 130.0]) and [f for _, f in plain] == [0.5, 0.3, 0.2]
    # 115.44-122.36 is the band; 112 and 125 lie outside it, 119 and 117 inside -> the nearest, 117
    assert targets(s, S7TradeParams(), np.array([112.0, 119.0, 117.0, 125.0]))[1][0] == pytest.approx(117.0)
    short = targets(short_setup(), S7TradeParams(), np.array([83.0, 81.0]))  # band 84.56 down to 77.64 -> nearest 83
    assert [p for p, _ in short] == pytest.approx([90.0, 83.0, 70.0])


def test_e1_needs_the_zone_reached_then_a_close_back_above_fib_half():
    os_ = orient(long_setup())
    low = np.array([104.0, 99.0, 99.5, 100.5])
    close = np.array([105.0, 99.8, 100.4, 101.0])
    assert e1_trigger(os_, low, close, touched=False) == (2, True)  # reached at 1 (close below 100), closes above at 2
    assert e1_trigger(os_, low[:2], close[:2], touched=False) == (None, True)
    assert e1_trigger(os_, np.array([104.0]), np.array([105.0]), touched=True) == (0, True)  # carried state
    assert e1_trigger(os_, np.array([104.0]), np.array([105.0]), touched=False) == (None, False)


def test_tf_cancellation_reasons():
    os_ = orient(long_setup())
    a_tr = np.full(3, 2.0)
    p = S7Params()
    o = np.array([105.0, 105.0, 105.0])
    assert tf_cancel_reason(os_, 0, o, np.array([89.0, 0, 0]), np.array([89.9, 0, 0]), None, a_tr, p) == "closed_below_level0"
    assert tf_cancel_reason(os_, 0, o, np.array([97.0, 0, 0]), np.array([98.0, 0, 0]), None, a_tr, p) == "zone_broken_by_impulse"
    assert tf_cancel_reason(os_, 0, np.array([99.0]), np.array([97.0]), np.array([98.0]), None, a_tr, p) is None  # body 1 < 1 ATR (= 2)
    assert tf_cancel_reason(os_, 0, o, np.array([104.0, 0, 0]), np.array([110.5, 0, 0]), None, a_tr, p) == "level1_moved"
    assert s3_exit_index(os_, np.array([95.0, 91.0, 89.0, 92.0]), 0) == 2
    assert s3_exit_index(os_, np.array([95.0, 91.0, 89.0, 92.0]), 3) is None


def test_ladder_r_from_the_actual_fill():
    assert ladder_r(101.0, 89.5, 1, (110.0, 122.36, 130.0)) == pytest.approx((9 / 11.5, 21.36 / 11.5, 29 / 11.5))
    assert ladder_r(110.5, 89.5, 1, (110.0, 122.36, 130.0)) is None  # filled beyond TP1
    assert ladder_r(89.0, 89.5, 1, (110.0, 122.36, 130.0)) is None  # filled beyond the stop
    assert ladder_r(99.0, 110.5, -1, (90.0, 83.0, 70.0)) == pytest.approx((9 / 11.5, 16 / 11.5, 29 / 11.5))
