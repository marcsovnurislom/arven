"""Strategy S5 detection math (docs/strategy_range_breakout.md), hand-computed on tiny synthetic arrays."""

from __future__ import annotations

import numpy as np
import pytest

from arven.engine.strategy_s5 import (
    RangeState,
    breakout_side,
    build_decision,
    squeeze_range,
)


def _flat(n: int = 60, price: float = 100.0, half_range: float = 0.5):
    close = np.full(n, price)
    return close + half_range, close - half_range, close


def test_constant_range_is_a_squeeze_with_hand_computed_values():
    high, low, close = _flat()
    s = squeeze_range(high, low, close)
    assert s is not None
    assert s.hi == pytest.approx(100.5) and s.lo == pytest.approx(99.5)
    assert s.atr == pytest.approx(1.0)  # true range is 1.0 on every bar
    assert s.width == pytest.approx(1.0) and s.mid == pytest.approx(100.0) and s.buffer == pytest.approx(0.1)


def test_wide_range_is_not_a_squeeze():
    high, low, close = _flat()
    high[-5] = 120.0  # one spike inside the last 24 bars: width 20.5 vs ATR ~ 2.4
    assert squeeze_range(high, low, close) is None


def test_too_little_history_or_nan_gives_none():
    high, low, close = _flat(10)
    assert squeeze_range(high, low, close) is None
    high, low, close = _flat()
    high[-1] = np.nan
    assert squeeze_range(high, low, close) is None


def test_breakout_side_requires_fresh_close_beyond_edge_in_trend_direction():
    s = RangeState(100.5, 99.5, 1.0)  # up = 100.6, down = 99.4
    assert breakout_side(101.0, 100.0, s, slope=1.0) == 1
    assert breakout_side(101.0, 100.7, s, slope=1.0) == 0  # previous close already beyond: not fresh
    assert breakout_side(101.0, 100.0, s, slope=-1.0) == 0  # against the 4h trend
    assert breakout_side(101.0, 100.0, s, slope=0.0) == 0
    assert breakout_side(99.0, 100.0, s, slope=-1.0) == -1
    assert breakout_side(100.55, 100.0, s, slope=1.0) == 0  # inside the buffer
    assert breakout_side(float("nan"), 100.0, s, slope=1.0) == 0


def test_long_decision_hand_computed():
    s = RangeState(100.5, 99.5, 1.0)
    d = build_decision(1, 101.0, s)
    assert d is not None
    assert d.stop == pytest.approx(99.75)  # mid 100 - 0.25 * ATR
    assert [t.price for t in d.targets] == pytest.approx([102.0, 102.5, 103.0])  # entry + k * width
    assert [t.r_multiple for t in d.targets] == pytest.approx([0.8, 1.2, 1.6])  # risk = 1.25
    assert [t.close_fraction for t in d.targets] == [0.5, 0.3, 0.2]
    assert d.confidence == pytest.approx(0.75)  # 1 - 1 / 4


def test_short_decision_is_symmetric_with_positive_r_multiples():
    s = RangeState(100.5, 99.5, 1.0)
    d = build_decision(-1, 99.0, s)
    assert d is not None
    assert d.stop == pytest.approx(100.25)
    assert [t.price for t in d.targets] == pytest.approx([98.0, 97.5, 97.0])
    assert all(t.r_multiple > 0 for t in d.targets)
    assert d.targets[0].r_multiple == pytest.approx(0.8)
