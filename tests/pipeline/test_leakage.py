"""Causal correctness of the full Stage 5 pipeline through the real Stage 4 engine.

The individual causality guarantees already exist at lower layers (FeatureView refuses future rows; the
Stage 3 features and Stage 4 execution both have their own leakage suites) — these tests exercise the
*composition*: the regime detector's sequential state, the three strategies, the decision engine and the
risk engine's circuit-breaker state, all driven through one real backtest run, must be prefix-invariant and
insensitive to perturbing anything after the cut time, on both the feature side and the raw 1m market side.
"""

import pytest
from bt_helpers import bt_config, garbage_after, make_market as bt_make_market, truncate_market, window, zero_cost_app
from pipeline_helpers import garbage_features_after, make_feature_data, make_pipeline, truncate_features

from arven.backtest.engine import Backtester

HOUR = 3_600_000
SEEDS = [1, 4, 9, 15, 22]


def _run(days, market, feats, hours=None):
    hrs = hours if hours is not None else days * 24
    return Backtester(zero_cost_app(), bt_config(), window(hrs, market.window_start_ms), market, feats).run(make_pipeline())


def _trade_key(t):
    return (t.entry_time_ms, t.exit_time_ms, t.exit_reason.value, round(t.qty, 9), round(t.net_pnl, 8))


@pytest.mark.parametrize("seed", SEEDS)
def test_prefix_invariance_of_the_full_pipeline(seed):
    days = 250
    feats = make_feature_data(days, seed)
    market = bt_make_market(days * 24)
    cut_days = days // 2
    cut_ms = market.window_start_ms + cut_days * 24 * HOUR

    full = _run(days, market, feats)
    part = _run(days, truncate_market(market, cut_days * 24), truncate_features(feats, cut_days * 24), hours=cut_days * 24)

    full_done = [_trade_key(t) for t in full.trades if t.exit_time_ms < cut_ms]
    part_done = [_trade_key(t) for t in part.trades if t.exit_reason.value != "END_OF_PERIOD"]
    assert part_done == full_done

    fd = {p.time_ms: p.equity for p in full.equity if p.kind.value == "DECISION" and p.time_ms < cut_ms}
    pd_ = {p.time_ms: p.equity for p in part.equity if p.kind.value == "DECISION"}
    assert fd.keys() == pd_.keys()
    for t in fd:
        assert fd[t] == pytest.approx(pd_[t], rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
def test_perturbation_after_the_cut_changes_nothing_before_it(seed):
    days = 250
    feats = make_feature_data(days, seed)
    market = bt_make_market(days * 24)
    cut_days = days // 2
    cut_ms = market.window_start_ms + cut_days * 24 * HOUR

    base = _run(days, market, feats)
    pert = _run(days, garbage_after(market, cut_days * 24), garbage_features_after(feats, cut_days * 24), hours=days * 24)

    base_before = [_trade_key(t) for t in base.trades if t.exit_time_ms <= cut_ms]
    pert_before = [_trade_key(t) for t in pert.trades if t.exit_time_ms <= cut_ms]
    assert base_before == pert_before

    b = {p.time_ms: p.equity for p in base.equity if p.kind.value == "DECISION" and p.time_ms <= cut_ms}
    q = {p.time_ms: p.equity for p in pert.equity if p.kind.value == "DECISION" and p.time_ms <= cut_ms}
    assert b == pytest.approx(q, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("seed", SEEDS[:3])
def test_regime_sequence_up_to_the_cut_is_identical_under_perturbation(seed):
    """The regime detector's own hysteresis state must not be influenced by anything after the cut."""
    days = 250
    feats = make_feature_data(days, seed)
    market = bt_make_market(days * 24)
    cut_days = days // 2

    base_pipe = make_pipeline()
    Backtester(zero_cost_app(), bt_config(), window(days * 24), market, feats).run(base_pipe)
    pert_pipe = make_pipeline()
    Backtester(zero_cost_app(), bt_config(), window(days * 24), garbage_after(market, cut_days * 24), garbage_features_after(feats, cut_days * 24), stress=False).run(pert_pipe)

    cut_hours = cut_days * 24
    base_regimes = [r.regime.label for r in base_pipe.history[:cut_hours]]
    pert_regimes = [r.regime.label for r in pert_pipe.history[:cut_hours]]
    assert base_regimes == pert_regimes
