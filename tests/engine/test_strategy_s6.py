"""Strategy S6 detection math (docs/strategy_trend_pullback.md), hand-computed on tiny synthetic arrays."""

from __future__ import annotations

import numpy as np
import pytest

from arven.engine.strategy_s6 import PullbackState, bounce_fires, build_decision, pullback_ok, pullback_state


def _hourly(n: int = 60):
    close = np.full(n, 100.0)
    close[-3:] = 100.4
    return close + 0.5, close - 0.5, close


def test_pullback_state_hand_computed():
    high, low, close = _hourly()
    s = pullback_state(high, low, close)
    assert s is not None
    assert s.atr == pytest.approx(1.0)  # true range is 1.0 on every bar
    assert s.pull_low == pytest.approx(99.5) and s.pull_high == pytest.approx(100.9)
    assert s.last_close == pytest.approx(100.4)
    assert 100.0 < s.ema < 100.4  # three closes above a flat 100 pull the EMA(20) just above 100


def test_too_little_history_gives_none():
    high, low, close = _hourly(10)
    assert pullback_state(high, low, close) is None


def test_pullback_ok_long_and_short():
    s = PullbackState(ema=100.1, atr=1.0, last_close=100.4, pull_low=99.5, pull_high=100.9)
    assert pullback_ok(1, s)  # touched the average (99.5 <= 100.35) and holds above it
    assert not pullback_ok(-1, s)  # close above the EMA
    far = PullbackState(ema=100.1, atr=1.0, last_close=100.4, pull_low=100.6, pull_high=101.0)
    assert not pullback_ok(1, far)  # never came down to the average
    below = PullbackState(ema=100.1, atr=1.0, last_close=99.7, pull_low=99.0, pull_high=100.2)
    assert pullback_ok(-1, below) and not pullback_ok(1, below)


def test_bounce_requires_a_fresh_close_beyond_the_previous_four_bars():
    high = np.array([100.1, 100.1, 100.1, 100.1, 100.1, 100.6])
    low = high - 0.2
    close = np.array([100.0, 100.0, 100.0, 100.0, 100.0, 100.5])
    assert bounce_fires(1, high, low, close)
    stale_close = np.array([100.0, 100.0, 100.0, 100.0, 100.3, 100.5])  # previous close already above its own level
    assert not bounce_fires(1, high, low, stale_close)
    assert not bounce_fires(-1, high, low, close)
    assert not bounce_fires(1, high[:4], low[:4], close[:4])  # too little history


def test_bounce_short_is_the_mirror_image():
    low = np.array([99.9, 99.9, 99.9, 99.9, 99.9, 99.4])
    high = low + 0.2
    close = np.array([100.0, 100.0, 100.0, 100.0, 100.0, 99.5])
    assert bounce_fires(-1, high, low, close)


def test_long_decision_hand_computed():
    s = PullbackState(ema=100.1, atr=1.0, last_close=100.4, pull_low=99.5, pull_high=100.9)
    d = build_decision(1, 100.5, s)
    assert d is not None
    assert d.stop == pytest.approx(99.25)  # min(99.5 - 0.25, 100.5 - 1.0)
    assert [t.price for t in d.targets] == pytest.approx([100.5 + 1.5 * 1.25, 100.5 + 2.5 * 1.25, 100.5 + 4.0 * 1.25])
    assert [t.close_fraction for t in d.targets] == [0.5, 0.3, 0.2]


def test_stop_is_never_tighter_than_one_atr_and_short_is_symmetric():
    s = PullbackState(ema=100.1, atr=1.0, last_close=100.4, pull_low=100.2, pull_high=100.9)
    long_d = build_decision(1, 100.5, s)
    assert long_d.stop == pytest.approx(99.5)  # pull_low - 0.25 = 99.95 would be tighter than entry - 1 ATR
    short_d = build_decision(-1, 99.9, s)
    assert short_d.stop == pytest.approx(101.15)  # max(100.9 + 0.25, 99.9 + 1.0)
    assert all(t.price < 99.9 for t in short_d.targets)
