"""The S6 SignalProvider adapter wired end to end on a hand-built pullback-then-bounce scenario."""

from __future__ import annotations

import numpy as np
import pytest

from arven.backtest.provider import DecisionContext, PortfolioSnapshot
from arven.backtest.strategy_s6_provider import STRATEGY_ID, TrendPullbackProvider, make_spec
from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.core.types import Action

MIN15 = 900_000
HOUR = 3_600_000
J = 5400  # the bounce bar; it closes (becomes available) at (J + 1) * 15m = hour 1350.25
N_SETUP, N_CTX, N_TRIG = 1410, 412, 5640


def _series(tf: Timeframe, n: int, price: np.ndarray, half_range: float) -> BarSeries:
    t = np.arange(n) * tf.ms
    ones = np.ones(n)
    return BarSeries(tf, 0, t, price.copy(), price + half_range, price - half_range, price.copy(), ones, ones, ones, np.ones(n, dtype=bool))


def _context(drift4h: float) -> BarSeries:
    return _series(Timeframe.H4, N_CTX, 100.0 + np.arange(N_CTX) * drift4h, 0.01)


def build(drift4h: float = 0.05) -> tuple[TrendPullbackProvider, int]:
    p1h = np.full(N_SETUP, 100.0)
    p1h[1347:1350] = 100.4  # the last three closed 1h bars hold just above the flat average
    setup = _series(Timeframe.H1, N_SETUP, p1h, 0.5)
    p15 = np.full(N_TRIG, 100.0)
    p15[J] = 100.5
    trigger = _series(Timeframe.M15, N_TRIG, p15, 0.01)
    return TrendPullbackProvider(setup, trigger, _context(drift4h)), (J + 1) * MIN15


def ctx(now_ms: int, **kw) -> DecisionContext:
    base = dict(equity=10_000.0, wallet=10_000.0, side=0, qty=0.0, entry_price=0.0, unrealized=0.0, available_margin=10_000.0, order_pending=False)
    base.update(kw)
    return DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=PortfolioSnapshot(**base), period="development")


def test_rejects_wrong_timeframes():
    provider, _ = build()
    with pytest.raises(ValueError):
        TrendPullbackProvider(provider._setup_bars, provider._trigger_bars, provider._setup_bars)


def test_pullback_and_bounce_in_an_uptrend_fires_a_consistent_signal_and_engine_signal():
    provider, now_ms = build()
    signal = provider.decide(ctx(now_ms))
    assert signal is not None and signal.action == Action.LONG and signal.t_ms == now_ms
    assert signal.stop_pct == pytest.approx(1.25 / 100.5)
    assert signal.take_profit_pct == pytest.approx(1.875 / 100.5)
    es = provider.to_engine_signal(now_ms, feature_version="v1", config_hash="h", git_commit=None)
    assert es is not None and es.side == 1 and es.strategy_id == STRATEGY_ID and len(es.tp_ladder) == 3
    assert es.stop == pytest.approx(99.25) and es.tp_ladder[0].price == pytest.approx(100.5 + 1.875)


def test_downtrend_makes_the_same_pattern_a_non_signal():
    provider, now_ms = build(drift4h=-0.05)
    assert provider.decide(ctx(now_ms)) is None  # a short needs the 1h close below the average


def test_cooldown_blocks_a_second_signal_for_eight_hours():
    provider, now_ms = build()
    assert provider.decide(ctx(now_ms)) is not None
    assert provider._compute_decision(now_ms) is None  # inside the cooldown
    provider._last_signal_ms = now_ms - 9 * HOUR
    assert provider._compute_decision(now_ms) is not None


def test_no_signal_while_a_position_is_open_or_an_order_pending():
    provider, now_ms = build()
    assert provider.decide(ctx(now_ms, side=1, qty=1.0, entry_price=100.0)) is None
    assert provider.decide(ctx(now_ms, order_pending=True)) is None
    assert provider.to_engine_signal(now_ms, feature_version="v1", config_hash="h", git_commit=None) is None


def test_no_signal_on_the_bar_after_the_bounce_bar():
    provider, now_ms = build()
    assert provider._compute_decision(now_ms + MIN15) is None  # previous close is already above its level: not fresh


def test_insufficient_setup_history_gives_no_signal():
    provider, _ = build()
    assert provider._compute_decision(100 * HOUR) is None


def test_truncation_invariance_future_bars_never_change_a_decision():
    provider, now_ms = build()
    cut = TrendPullbackProvider(
        provider._setup_bars.available_until(now_ms), provider._trigger_bars.available_until(now_ms), _context(0.05),
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
