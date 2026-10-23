"""The "1000 universes" control (arven.backtest.universes): templates, one random trade by hand, reproducibility, the
account curve, thinning and the percentile."""

from __future__ import annotations

import numpy as np
import pytest
from bt_helpers import make_market, zero_cost_app

from arven.backtest.account_sim import AccountRules
from arven.backtest.universes import (
    RandomTrade, TradeTemplate, equity_curve, percentile_of, random_trade, thin, universe, verdict,
)

COSTS = zero_cost_app().costs


def rising(hours: int = 6, step: float = 0.001):
    """Price up ``step`` per minute from 30 000: o = previous close, a tiny wick."""
    bars, p = {}, 30_000.0
    for k in range(hours * 60):
        c = p * (1 + step)
        bars[k] = (p, c, p, c)
        p = c
    return make_market(hours, bars)


def walk(hours: int = 48, seed: int = 3):
    rng = np.random.default_rng(seed)
    bars, p = {}, 30_000.0
    for k in range(hours * 60):
        c = p * (1 + rng.normal(0, 0.002))
        bars[k] = (p, max(p, c) * 1.0005, min(p, c) * 0.9995, c)
        p = c
    return make_market(hours, bars)


def test_template_copies_side_stop_distance_and_ladder_in_r():
    t = TradeTemplate.from_trade(1, 100.0, 98.0, [102.0, 104.0, 106.0])
    assert t == TradeTemplate(1, 0.02, (1.0, 2.0, 3.0))
    s = TradeTemplate.from_trade(-1, 100.0, 101.0, [99.0, 98.0])
    assert s is not None and s.ladder_r == (1.0, 2.0) and s.stop_fraction == pytest.approx(0.01)
    assert TradeTemplate.from_trade(1, 100.0, 101.0, [102.0]) is None  # stop on the wrong side
    assert TradeTemplate.from_trade(1, 100.0, 98.0, []) is None  # a time exit: nothing to copy


def test_a_random_long_in_a_steady_rise_takes_every_target_by_hand():
    m = rising()
    t = TradeTemplate(1, 0.01, (1.0, 2.0, 3.0))
    x = random_trade(t, m, 10, COSTS, "BTCUSDT")
    assert x is not None and x.entry_time_ms == int(m.time_ms[10])
    assert x.net_r == pytest.approx(0.5 * 1 + 0.3 * 2 + 0.2 * 3, abs=0.02)  # zero costs: 1.7 R (targets hit within a bar)
    assert x.risk_per_unit == pytest.approx(float(m.open[10]) * 0.01)
    short = random_trade(TradeTemplate(-1, 0.01, (1.0,)), m, 10, COSTS, "BTCUSDT")
    assert short is not None and short.net_r == pytest.approx(-1.0, abs=0.02)  # stopped out


def test_universes_are_reproducible_from_the_seed():
    m = walk()
    tpl = [TradeTemplate(1, 0.005, (1.0, 2.0, 3.0)), TradeTemplate(-1, 0.004, (1.5, 2.5)), TradeTemplate(1, 0.006, (2.0,))] * 4
    a = universe(tpl, m, np.random.default_rng([7, 1]), COSTS, "BTCUSDT", horizon_ms=6 * 3_600_000)
    b = universe(tpl, m, np.random.default_rng([7, 1]), COSTS, "BTCUSDT", horizon_ms=6 * 3_600_000)
    c = universe(tpl, m, np.random.default_rng([7, 2]), COSTS, "BTCUSDT", horizon_ms=6 * 3_600_000)
    assert a == b and a != c and len(a) >= 6
    assert [x.entry_time_ms for x in a] == sorted(x.entry_time_ms for x in a)


def test_equity_curve_starts_at_the_balance_and_has_one_point_per_trade():
    rules = AccountRules()
    curve = equity_curve([RandomTrade(1, 300.0, 2.0), RandomTrade(2, 300.0, -1.0)], rules)
    assert len(curve) == 3 and curve[0] == 1000.0 and curve[1] > 1000.0 and curve[2] < curve[1]


def test_thin_keeps_both_ends_and_at_most_the_asked_points():
    c = list(range(1001))
    t = thin(c, 100)
    assert t[0] == 0 and t[-1] == 1000 and len(t) <= 100 and t == sorted(t)
    assert thin([1, 2, 3], 100) == [1, 2, 3]


def test_percentile_and_verdict():
    sample = list(range(100))
    assert percentile_of(50, sample) == 50.5  # 50 below, one tie counted half
    assert percentile_of(1000, sample) == 100.0 and percentile_of(-1, sample) == 0.0
    assert verdict(95.0, 30) == "skill_candidate" and verdict(94.9, 30) == "luck" and verdict(100.0, 7) == "too_few"
