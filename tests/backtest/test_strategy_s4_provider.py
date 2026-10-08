"""Phase 7b: the SignalProvider adapter for strategy S4, wired end to end (truncation, the 4h MultiTFView
context lookup, and both Signal/EngineSignal renderings of the same decision) against a hand-built
synthetic impulse-retest scenario - not re-verifying the detection math itself (hand-tested exhaustively in
tests/engine/test_strategy_s4.py), only that the adapter wires it together correctly.
"""

from __future__ import annotations

import numpy as np
import pytest

from arven.backtest.provider import DecisionContext, PortfolioSnapshot
from arven.backtest.strategy_s4_provider import MIN_SETUP_BARS, STRATEGY_ID, ImpulseRetestProvider, make_spec
from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.core.types import Action

HOUR = 3_600_000
MIN15 = 900_000


def _flat_series(tf: Timeframe, n: int, *, base: float = 100.0, drift_per_bar: float = 0.0, start_ms: int = 0) -> BarSeries:
    t = start_ms + np.arange(n) * tf.ms
    price = base + np.arange(n) * drift_per_bar
    o, c = price.copy(), price.copy()
    h, l = price + 0.01, price - 0.01  # noqa: E741
    ones = np.ones(n)
    return BarSeries(tf, 0, t, o, h, l, c, ones, ones, ones, np.ones(n, dtype=bool))


def _flat_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(equity=10_000.0, wallet=10_000.0, side=0, qty=0.0, entry_price=0.0, unrealized=0.0, available_margin=10_000.0, order_pending=False)


def build_firing_scenario(*, drift4h: float = 0.05) -> tuple[ImpulseRetestProvider, int]:
    """A hand-built bullish impulse-retest-trigger pattern, with enough warmup on every timeframe that
    the 4h context row is never stale. Returns the provider and the exact ``now_ms`` at which it fires.

    Construction notes (why these specific numbers): the 1h series drifts gently upward throughout so the
    4h `ema_slope_50` context filter (spec section 1.1) is unambiguously positive by the time of the
    pattern; a swing low, a >=3xATR impulse up, two pullback swing highs (for the trendline), and a 15m
    retest-and-hold into the Fibonacci zone are spliced in near the end. `N_CTX` deliberately spans more
    real time than `N_SETUP`'s own hours (a shorter context series was tried first and produced a `stale`
    4h row, found and fixed before writing this as a committed test - see `docs/current_state.md`'s
    "Phase 7b" section)."""
    n_setup = 1410
    n_ctx = n_setup // 4 + 60
    n_trig = n_setup * 4
    drift1h = drift4h / 4
    drift15m = drift4h / 16

    context = _flat_series(Timeframe.H4, n_ctx, drift_per_bar=drift4h)
    setup_raw = _flat_series(Timeframe.H1, n_setup, drift_per_bar=drift1h)
    trigger_raw = _flat_series(Timeframe.M15, n_trig, drift_per_bar=drift15m)

    o, h, l, c = setup_raw.open.copy(), setup_raw.high.copy(), setup_raw.low.copy(), setup_raw.close.copy()  # noqa: E741
    n = len(setup_raw)
    base_idx = n - 40
    l[base_idx], h[base_idx] = c[base_idx] - 3.0, c[base_idx] + 1.0
    low_idx = base_idx + 1
    l[low_idx] = c[low_idx] - 5.0
    for k in (low_idx - 2, low_idx - 1, low_idx + 1, low_idx + 2):
        l[k] = max(l[k], l[low_idx] + 1.0)
    high_idx = low_idx + 6
    impulse_size = 30.0
    h[high_idx] = l[low_idx] + impulse_size
    c[high_idx] = h[high_idx]
    for k in (high_idx - 2, high_idx - 1, high_idx + 1, high_idx + 2):
        h[k] = min(h[k], h[high_idx] - 1.0)
    p1_idx, p2_idx = high_idx + 4, high_idx + 8
    h[p1_idx], h[p2_idx] = h[high_idx] - 5.0, h[high_idx] - 8.0
    for k in (p1_idx - 2, p1_idx - 1, p1_idx + 1, p1_idx + 2):
        h[k] = min(h[k], h[p1_idx] - 1.0)
    for k in (p2_idx - 2, p2_idx - 1, p2_idx + 1, p2_idx + 2):
        h[k] = min(h[k], h[p2_idx] - 1.0)
    zone_price = h[high_idx] - 0.55 * impulse_size
    for k in range(high_idx + 1, min(p2_idx + 10, n)):
        c[k], o[k] = zone_price, zone_price
        h[k] = max(h[k], zone_price + 0.5)
        l[k] = min(l[k], zone_price - 0.5)
    h = np.maximum(h, np.maximum(o, c) + 0.01)
    l = np.minimum(l, np.minimum(o, c) - 0.01)
    setup = BarSeries(Timeframe.H1, 0, setup_raw.open_time_ms, o, h, l, c, setup_raw.volume, setup_raw.trade_count, setup_raw.taker_buy_volume, setup_raw.complete)

    as_of = p2_idx + 3
    decision_time_ms = int(setup.open_time_ms[as_of])

    oc, hc, lc, cc = trigger_raw.open.copy(), trigger_raw.high.copy(), trigger_raw.low.copy(), trigger_raw.close.copy()
    end15 = int(np.searchsorted(trigger_raw.open_time_ms, decision_time_ms, side="right"))
    zone_upper_guess = zone_price + 1.0  # the real zone is recomputed by the provider; this only needs to be "near" it
    for k in range(end15 - 20, end15):
        cc[k] = zone_upper_guess + 15.0
        oc[k], hc[k], lc[k] = cc[k], cc[k] + 0.2, cc[k] - 0.2
    cc[end15 - 1] = zone_upper_guess - 1.0
    oc[end15 - 1] = zone_upper_guess + 1.0
    hc[end15 - 1] = zone_upper_guess + 1.2
    lc[end15 - 1] = zone_upper_guess - 3.0
    hc = np.maximum(hc, np.maximum(oc, cc) + 0.01)
    lc = np.minimum(lc, np.minimum(oc, cc) - 0.01)
    trigger = BarSeries(Timeframe.M15, 0, trigger_raw.open_time_ms, oc, hc, lc, cc, trigger_raw.volume, trigger_raw.trade_count, trigger_raw.taker_buy_volume, trigger_raw.complete)

    provider = ImpulseRetestProvider(setup, trigger, context)
    now_ms = decision_time_ms + MIN15  # the retest bar's own close/availability time
    return provider, now_ms


def test_rejects_wrong_timeframes():
    h1 = _flat_series(Timeframe.H1, 10)
    m15 = _flat_series(Timeframe.M15, 10)
    h4 = _flat_series(Timeframe.H4, 10)
    with pytest.raises(ValueError):
        ImpulseRetestProvider(m15, h1, h4)  # setup/trigger swapped
    with pytest.raises(ValueError):
        ImpulseRetestProvider(h1, m15, h1)  # context is not 4h


def test_describe_names_the_strategy():
    h1, m15, h4 = _flat_series(Timeframe.H1, 10), _flat_series(Timeframe.M15, 10), _flat_series(Timeframe.H4, 10)
    d = ImpulseRetestProvider(h1, m15, h4).describe()
    assert d["name"] == STRATEGY_ID


def test_insufficient_warmup_returns_none():
    h1 = _flat_series(Timeframe.H1, MIN_SETUP_BARS - 1)
    m15 = _flat_series(Timeframe.M15, (MIN_SETUP_BARS - 1) * 4)
    h4 = _flat_series(Timeframe.H4, 400)
    provider = ImpulseRetestProvider(h1, m15, h4)
    now_ms = int(h1.open_time_ms[-1])
    ctx = DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=_flat_portfolio(), period="development")
    assert provider.decide(ctx) is None


def test_full_scenario_fires_a_consistent_signal_and_engine_signal():
    provider, now_ms = build_firing_scenario()
    ctx = DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=_flat_portfolio(), period="development")
    signal = provider.decide(ctx)
    assert signal is not None
    assert signal.t_ms == now_ms
    assert signal.action == Action.LONG
    assert signal.stop_pct is not None and 0 < signal.stop_pct < 1
    assert signal.take_profit_pct is not None and signal.take_profit_pct > signal.stop_pct  # TP1 further than stop
    assert signal.notional_fraction == pytest.approx(0.01 / signal.stop_pct)  # RISK_FRACTION / stop_pct
    assert provider.placed == 1

    engine_signal = provider.to_engine_signal(now_ms, feature_version="v1", config_hash="h", git_commit="abc")
    assert engine_signal is not None
    assert engine_signal.side == 1 and engine_signal.symbol == "BTCUSDT"
    assert engine_signal.strategy_id == STRATEGY_ID
    assert len(engine_signal.tp_ladder) == 3
    assert [lvl.r_multiple for lvl in engine_signal.tp_ladder] == sorted(lvl.r_multiple for lvl in engine_signal.tp_ladder)
    # the legacy Signal's own stop/TP1 must agree with the EngineSignal's richer entry/stop/TP1 geometry.
    assert signal.stop_pct == pytest.approx(abs(engine_signal.entry_reference - engine_signal.stop) / engine_signal.entry_reference)
    assert signal.take_profit_pct == pytest.approx(
        abs(engine_signal.tp_ladder[0].price - engine_signal.entry_reference) / engine_signal.entry_reference
    )


def test_no_signal_proposed_while_a_position_is_already_open():
    provider, now_ms = build_firing_scenario()
    open_portfolio = PortfolioSnapshot(equity=10_000.0, wallet=10_000.0, side=1, qty=1.0, entry_price=100.0, unrealized=0.0, available_margin=5_000.0, order_pending=False)
    ctx = DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=open_portfolio, period="development")
    assert provider.decide(ctx) is None


def test_no_signal_proposed_while_an_order_is_pending():
    provider, now_ms = build_firing_scenario()
    pending = PortfolioSnapshot(equity=10_000.0, wallet=10_000.0, side=0, qty=0.0, entry_price=0.0, unrealized=0.0, available_margin=10_000.0, order_pending=True)
    ctx = DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=pending, period="development")
    assert provider.decide(ctx) is None


def test_4h_context_disagreement_blocks_an_otherwise_valid_setup():
    # the same bullish pattern, but the 4h series now drifts *down* - section 1.1's context filter must
    # block a long whose direction disagrees with the larger trend, however clean the rest of the pattern.
    provider, now_ms = build_firing_scenario(drift4h=-0.05)
    ctx = DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=_flat_portfolio(), period="development")
    assert provider.decide(ctx) is None


def test_to_engine_signal_is_none_when_no_decision_was_just_made():
    provider, now_ms = build_firing_scenario()
    # decide() never called yet - no decision cached.
    assert provider.to_engine_signal(now_ms, feature_version="v1", config_hash="h", git_commit=None) is None
    # and after a None-returning decide() (already in position), the cache clears too.
    open_portfolio = PortfolioSnapshot(equity=10_000.0, wallet=10_000.0, side=1, qty=1.0, entry_price=100.0, unrealized=0.0, available_margin=5_000.0, order_pending=False)
    ctx = DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=open_portfolio, period="development")
    provider.decide(ctx)
    assert provider.to_engine_signal(now_ms, feature_version="v1", config_hash="h", git_commit=None) is None


def test_make_spec_matches_the_documented_timeframes():
    spec = make_spec()
    assert spec.context_tfs == (Timeframe.H4,) and spec.setup_tf == Timeframe.H1 and spec.trigger_tf == Timeframe.M15


def test_hourly_setup_cache_never_changes_a_decision():
    """The setup-side cache (keyed by the truncated 1h array's length) must be a pure speed-up: ticking one
    provider through consecutive 15m marks gives exactly the decisions fresh providers give at those marks."""
    cached, now_ms = build_firing_scenario()
    for k in range(10, -1, -1):
        t = now_ms - k * 900_000
        fresh, _ = build_firing_scenario()
        assert repr(cached._compute_decision(t)) == repr(fresh._compute_decision(t)), t
