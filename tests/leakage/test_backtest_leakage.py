"""Backtest-level causality: nothing a decision or a fill produces may depend on data after it.

- FeatureView / clock guards
- prefix invariance: cutting all data at T leaves every trade closed before T and every decision equity up to T unchanged
- perturbation: replacing everything after T with garbage changes nothing decided or completed at or before T
- fills happen at the open of the bar at t + latency, never at the close of the signal bar
- a provider with (test-only) access to the future is detected by its impossible results, while random signals lose ~costs
"""

import numpy as np
import pytest
from bt_helpers import (
    HOUR,
    T0,
    Scripted,
    app_config,
    bt_config,
    features_for,
    garbage_after,
    long_signal,
    make_market,
    truncate_market,
    window,
    zero_cost_app,
)
from bt_scenarios import random_scenario

from arven.backtest.baselines import RandomEntry
from arven.backtest.clock import SimulationClock
from arven.backtest.engine import Backtester
from arven.backtest.errors import ConfigurationError, DataError, LookAheadError, SignalError
from arven.backtest.provider import FeatureView, PrepareInfo
from arven.backtest.metrics import compute_metrics
from arven.core.signal import Signal
from arven.core.types import Action


# --- FeatureView and clock ----------------------------------------------------------------------


def make_view(hours=10):
    grid = T0 + np.arange(hours, dtype=np.int64) * HOUR
    clock = SimulationClock(grid)
    values = np.arange(hours * 2, dtype=float).reshape(hours, 2)
    return clock, FeatureView(grid, ("a", "b"), values, clock, T0)


def test_feature_view_refuses_future_rows_and_allows_past_and_now():
    clock, view = make_view()
    clock.advance()
    clock.advance()
    clock.advance()  # now = T0 + 2h
    assert view.value("a") == 4.0 and view.value("a", T0 + HOUR) == 2.0 and view.value("b", T0) == 1.0
    with pytest.raises(LookAheadError):
        view.value("a", T0 + 3 * HOUR)
    with pytest.raises(LookAheadError):
        view.row(T0 + 9 * HOUR)
    with pytest.raises(KeyError):
        view.value("a", T0 - HOUR)
    np.testing.assert_array_equal(view.history("a", 5), [0.0, 2.0, 4.0])  # only rows <= now, oldest first


def test_feature_view_bound_to_the_clock_moves_with_it():
    clock, view = make_view()
    clock.advance()
    with pytest.raises(LookAheadError):
        view.value("a", T0 + HOUR)
    clock.advance()
    assert view.value("a", T0 + HOUR) == 2.0


def test_clock_rules():
    clock = SimulationClock(T0 + np.arange(3, dtype=np.int64) * HOUR)
    with pytest.raises(RuntimeError):
        clock.now_ms
    assert [clock.advance(), clock.advance(), clock.advance(), clock.advance()] == [T0, T0 + HOUR, T0 + 2 * HOUR, None]
    with pytest.raises(ValueError):
        SimulationClock(np.array([T0 + HOUR, T0], dtype=np.int64))
    with pytest.raises(ValueError):
        SimulationClock(np.array([T0 + 1], dtype=np.int64))


class Peeker:
    def describe(self):
        return {"name": "peeker"}

    def prepare(self, info):
        return None

    def decide(self, ctx):
        ctx.features.value("feat_ready", ctx.now_ms + HOUR)  # tries to read the next row
        return None


def test_provider_peeking_at_the_next_feature_row_aborts_the_run():
    market = make_market(4)
    win = window(4)
    with pytest.raises(LookAheadError):
        Backtester(zero_cost_app(), bt_config(), win, market, features_for(win)).run(Peeker())


# --- engine guards ------------------------------------------------------------------------------


def test_engine_rejects_inconsistent_inputs_and_configs():
    market = make_market(4)
    win = window(4)
    feats = features_for(win)
    with pytest.raises(DataError):  # market window differs from the allowed window
        Backtester(zero_cost_app(), bt_config(), window(3), market, features_for(window(3)))
    bad = features_for(window(3))
    with pytest.raises(DataError):  # feature rows do not match the decision grid
        Backtester(zero_cost_app(), bt_config(), win, market, bad)
    app = zero_cost_app()
    delayed = app.model_copy(update={"data": app.data.model_copy(update={"bar_availability_delay_seconds": 120})})
    with pytest.raises(ConfigurationError, match="latency"):
        Backtester(delayed, bt_config(latency_minutes=1), win, market, feats)
    maker = app_config(fees={"entry_order_type": "maker"})
    with pytest.raises(ConfigurationError, match="taker"):
        Backtester(maker, bt_config(), win, market, feats)


def test_signal_with_the_wrong_time_is_an_error():
    market = make_market(4)
    win = window(4)
    bad = Scripted({T0 + HOUR: Signal(T0, Action.LONG, notional_fraction=0.5)})
    with pytest.raises(SignalError):
        Backtester(zero_cost_app(), bt_config(), win, market, features_for(win)).run(bad)


# --- fills are at the next open ------------------------------------------------------------------


def test_entry_fills_at_the_open_of_the_next_bar_not_the_close_of_the_signal_bar():
    bars = {60: (31_000.0, 31_000.0, 31_000.0, 31_000.0)}  # the market gaps up exactly at the decision time
    market = make_market(3, bars)
    win = window(3)
    res = Backtester(zero_cost_app(), bt_config(), win, market, features_for(win)).run(Scripted({T0 + HOUR: long_signal(T0 + HOUR, 0.5)}))
    t = res.trades[0]
    assert market.close[59] == 30_000.0  # close of the last bar of the signal hour
    assert t.entry_ref_price == 31_000.0 and t.entry_time_ms == T0 + HOUR
    # the decision equity was marked at the last close before t, not at the fill price
    assert [p for p in res.equity if p.time_ms == T0 + HOUR and p.kind.value == "DECISION"][0].equity == 10_000.0


# --- prefix invariance and perturbation ----------------------------------------------------------

SEEDS = list(range(0, 300, 12))


def _run(market, signals, cfg, stress, hours):
    win = window(hours)
    return Backtester(app_config(), cfg, win, market, features_for(win), stress=stress).run(Scripted(signals))


def _trade_key(t):
    return (t.entry_time_ms, t.exit_time_ms, t.exit_reason.value, round(t.qty, 9), round(t.net_pnl, 8))


@pytest.mark.parametrize("seed", SEEDS)
def test_prefix_invariance(seed):
    hours, market, rates, signals, cfg, stress = random_scenario(seed)
    cut = max(hours // 2, 2)
    full = _run(market, signals, cfg, stress, hours)
    part = _run(truncate_market(market, cut), {t: s for t, s in signals.items() if t < T0 + cut * HOUR}, cfg, stress, cut)
    t_cut = T0 + cut * HOUR
    full_done = [_trade_key(t) for t in full.trades if t.exit_time_ms < t_cut]
    part_done = [_trade_key(t) for t in part.trades if t.exit_reason.value != "END_OF_PERIOD"]
    assert part_done == full_done
    fd = {p.time_ms: p.equity for p in full.equity if p.kind.value == "DECISION" and p.time_ms < t_cut}
    pd_ = {p.time_ms: p.equity for p in part.equity if p.kind.value == "DECISION"}
    assert fd.keys() == pd_.keys()
    for t in fd:
        assert fd[t] == pytest.approx(pd_[t], rel=1e-12, abs=1e-9)
    assert [f.time_ms for f in full.funding if f.time_ms < t_cut] == [f.time_ms for f in part.funding]


@pytest.mark.parametrize("seed", SEEDS)
def test_perturbation_after_t_changes_nothing_decided_or_completed_before_t(seed):
    hours, market, rates, signals, cfg, stress = random_scenario(seed)
    cut = max(hours // 2, 2)
    t_cut = T0 + cut * HOUR
    base = _run(market, signals, cfg, stress, hours)
    pert = _run(garbage_after(market, cut), signals, cfg, stress, hours)
    assert [_trade_key(t) for t in base.trades if t.exit_time_ms < t_cut] == [_trade_key(t) for t in pert.trades if t.exit_time_ms < t_cut]
    b = {p.time_ms: p.equity for p in base.equity if p.kind.value == "DECISION" and p.time_ms <= t_cut}
    q = {p.time_ms: p.equity for p in pert.equity if p.kind.value == "DECISION" and p.time_ms <= t_cut}
    assert b == pytest.approx(q, rel=1e-12, abs=1e-9)
    # entries decided before the cut are identical up to the fill bar (which lies after a decision at the cut)
    assert [e for e in base.orders if e.time_ms < t_cut] == [e for e in pert.orders if e.time_ms < t_cut]


# --- a provider with future access is caught; random signals lose ~costs -------------------------


def _random_walk_market(hours, seed):
    rng = np.random.default_rng(seed)
    px, bars = 30_000.0, {}
    for i in range(hours * 60):
        o = px
        px *= 1 + rng.normal(0, 4e-4)  # driftless
        bars[i] = (o, max(o, px) * 1.0002, min(o, px) * 0.9998, px)
    return make_market(hours, bars, funding_rates={T0 + k * 8 * HOUR: 0.0 for k in range(hours // 8 + 2)})


class Cheater:
    """Test-only: reads the future hour's close from the raw market and trades in its direction."""

    def __init__(self, market):
        self._m = market

    def describe(self):
        return {"name": "cheater"}

    def prepare(self, info):
        return None

    def decide(self, ctx):
        j = self._m.index_of(ctx.now_ms)
        if j < 0 or j + 60 >= len(self._m) or ctx.portfolio.side != 0:
            return None
        up = self._m.close[j + 59] > self._m.open[j]
        return Signal(ctx.now_ms, Action.LONG if up else Action.SHORT, notional_fraction=1.0, max_holding_minutes=60)


def test_a_cheating_provider_is_exposed_and_random_signals_lose_about_the_costs():
    hours = 24 * 30
    market = _random_walk_market(hours, 21)
    win = window(hours)
    app = app_config()
    bt = Backtester(app, bt_config(), win, market, features_for(win))
    cheat = compute_metrics(bt.run(Cheater(market)), bt_config())
    assert cheat["total_return"] > 0.3  # impossible for a causal signal on a driftless random walk after costs

    gross, net, costs, rets = [], [], [], []
    for i in range(24):
        prov = RandomEntry(base_seed=42, spawn_index=i, n_trades=120, holding_minutes=60, notional_fraction=1.0)
        res = bt.run(prov)
        m = compute_metrics(res, bt_config())
        gross.append(sum(t.gross_pnl for t in res.trades))
        net.append(m["net_pnl_usdt"])
        rets.append(m["total_return"])
        costs.append(m["fees_total"] + m["slippage_total"])
    assert cheat["total_return"] > max(rets) + 0.2  # far outside anything random signals produce
    se = np.std(gross, ddof=1) / np.sqrt(len(gross))
    assert abs(np.mean(gross)) < 4 * se  # no edge before costs
    assert np.mean(net) < 0  # so after costs the average random strategy loses
    assert np.mean(net) == pytest.approx(np.mean(gross) - np.mean(costs), rel=1e-6)  # ... by about the costs (funding is 0 here)
