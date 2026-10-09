"""The S5 SignalProvider adapter wired end to end on a hand-built squeeze-then-breakout scenario."""

from __future__ import annotations

import numpy as np
import pytest

from arven.backtest.provider import DecisionContext, PortfolioSnapshot
from arven.backtest.strategy_s5_provider import STRATEGY_ID, SqueezeBreakoutProvider, make_spec
from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.core.types import Action

MIN15 = 900_000
J = 5400  # index of the 15m bar that breaks out; it closes (becomes available) at (J + 1) * 15m


def _series(tf: Timeframe, n: int, price: np.ndarray, half_range: float) -> BarSeries:
    t = np.arange(n) * tf.ms
    ones = np.ones(n)
    return BarSeries(tf, 0, t, price.copy(), price + half_range, price - half_range, price.copy(), ones, ones, ones, np.ones(n, dtype=bool))


def build(drift4h: float = 0.05, *, break_up: bool = True) -> tuple[SqueezeBreakoutProvider, int]:
    n_setup, n_ctx, n_trig = 1410, 412, 5640
    setup = _series(Timeframe.H1, n_setup, np.full(n_setup, 100.0), 0.5)
    context = _series(Timeframe.H4, n_ctx, 100.0 + np.arange(n_ctx) * drift4h, 0.01)
    p15 = np.full(n_trig, 100.0)
    p15[J] = 101.0 if break_up else 99.0
    trigger = _series(Timeframe.M15, n_trig, p15, 0.01)
    return SqueezeBreakoutProvider(setup, trigger, context), (J + 1) * MIN15


def flat_portfolio(**kw) -> PortfolioSnapshot:
    base = dict(equity=10_000.0, wallet=10_000.0, side=0, qty=0.0, entry_price=0.0, unrealized=0.0, available_margin=10_000.0, order_pending=False)
    base.update(kw)
    return PortfolioSnapshot(**base)


def ctx(now_ms: int, **kw) -> DecisionContext:
    return DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=flat_portfolio(**kw), period="development")


def test_rejects_wrong_timeframes():
    provider, _ = build()
    h1 = provider._setup_bars
    with pytest.raises(ValueError):
        SqueezeBreakoutProvider(h1, provider._trigger_bars, h1)


def test_breakout_in_trend_direction_fires_a_consistent_signal_and_engine_signal():
    provider, now_ms = build()
    signal = provider.decide(ctx(now_ms))
    assert signal is not None and signal.action == Action.LONG and signal.t_ms == now_ms
    assert signal.stop_pct == pytest.approx(1.25 / 101.0)
    assert signal.take_profit_pct == pytest.approx(1.0 / 101.0)
    assert signal.notional_fraction == pytest.approx(0.01 / signal.stop_pct)
    es = provider.to_engine_signal(now_ms, feature_version="v1", config_hash="h", git_commit=None)
    assert es is not None and es.side == 1 and es.strategy_id == STRATEGY_ID and len(es.tp_ladder) == 3
    assert es.stop == pytest.approx(99.75) and es.tp_ladder[0].price == pytest.approx(102.0)


def test_breakout_against_the_4h_trend_is_ignored():
    provider, now_ms = build(drift4h=-0.05)
    assert provider.decide(ctx(now_ms)) is None


def test_downward_breakout_in_a_downtrend_is_a_short():
    provider, now_ms = build(drift4h=-0.05, break_up=False)
    signal = provider.decide(ctx(now_ms))
    assert signal is not None and signal.action == Action.SHORT


def test_no_signal_while_a_position_is_open_or_an_order_pending():
    provider, now_ms = build()
    assert provider.decide(ctx(now_ms, side=1, qty=1.0, entry_price=100.0)) is None
    assert provider.decide(ctx(now_ms, order_pending=True)) is None
    assert provider.to_engine_signal(now_ms, feature_version="v1", config_hash="h", git_commit=None) is None


def test_no_signal_on_the_bar_after_the_breakout_bar():
    provider, now_ms = build()
    assert provider.decide(ctx(now_ms + MIN15)) is None  # the previous close is already beyond the edge: not fresh


def test_insufficient_setup_history_gives_no_signal():
    provider, _ = build()
    assert provider.decide(ctx(100 * 3_600_000)) is None


def test_truncation_invariance_future_bars_never_change_a_decision():
    """The decision at now_ms from full-history series equals the one from series cut at now_ms."""
    provider, now_ms = build()
    cut = SqueezeBreakoutProvider(
        provider._setup_bars.available_until(now_ms), provider._trigger_bars.available_until(now_ms), _series(Timeframe.H4, 412, 100.0 + np.arange(412) * 0.05, 0.01),
    )
    assert repr(provider._compute_decision(now_ms)) == repr(cut._compute_decision(now_ms)) != "None"


def test_hourly_cache_never_changes_a_decision():
    cached, now_ms = build()
    for k in range(8, -1, -1):
        t = now_ms - k * MIN15
        fresh, _ = build()
        assert repr(cached._compute_decision(t)) == repr(fresh._compute_decision(t)), t


def test_make_spec_matches_the_documented_timeframes():
    spec = make_spec()
    assert spec.setup_tf == Timeframe.H1 and spec.trigger_tf == Timeframe.M15 and spec.context_tfs == (Timeframe.H4,)
