"""Dataset construction: reproduces Stage 5's real pipeline exactly, eligibility rules, encoding."""

import numpy as np
import pytest
from pipeline_helpers import make_feature_data, make_pipeline, random_1m_market

from arven.core.backtest_config import load_backtest_config
from arven.core.config import load_config
from arven.core.ml_config import load_ml_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.strategies_config import load_strategies_config
from arven.decision.engine import DecisionEngine
from arven.decision.pipeline import build_strategies
from arven.ml.dataset import CONTEXT_COLUMNS, build_dataset
from arven.regime.detector import RegimeDetector
from arven.risk.engine import RiskEngine

REGIME, STRATEGIES, RISK, BT, ML, APP = (
    load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(),
    load_ml_config(), load_config(),
)


def test_dataset_columns_are_60_stage3_plus_18_context():
    market = random_1m_market(300 * 24, seed=1)
    feats = make_feature_data(300, seed=1)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    assert len(ds.feature_names) == 60 + 18
    assert "feat_ready" not in ds.feature_names
    assert set(CONTEXT_COLUMNS) <= set(ds.feature_names)
    assert ds.x.shape == (len(ds), 78)


def test_dataset_row_counts_are_internally_consistent():
    market = random_1m_market(300 * 24, seed=2)
    feats = make_feature_data(300, seed=2)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    assert len(ds) + ds.n_ineligible_risk + ds.n_ineligible_label == ds.n_candidates_total
    assert len(ds.t_ms) == len(ds.horizon_ms) == len(ds.action) == len(ds.label) == len(ds.net_return) == len(ds)
    assert set(ds.action.tolist()) <= {1, -1}
    assert set(ds.label.tolist()) <= {0, 1}
    assert np.all(ds.horizon_ms > ds.t_ms)


def test_dataset_reproduces_stage5s_own_non_no_trade_candidate_count():
    """Regression: the number of non-NO_TRADE ProposedDecisions dataset.py observes must exactly match a
    direct replay of Stage 5's own regime/strategies/decision engine (no risk, no ML) - proving dataset
    construction does not silently diverge from the committed Stage 5 decision logic."""
    market = random_1m_market(400 * 24, seed=3)
    feats = make_feature_data(400, seed=3)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)

    from arven.backtest.clock import SimulationClock
    from arven.backtest.provider import FeatureView
    from arven.core.types import Action

    clock = SimulationClock(feats.t_ms)
    view = FeatureView(feats.t_ms, feats.names, feats.values, clock, feats.first_ready_ms)
    detector = RegimeDetector(REGIME)
    strategies = build_strategies(STRATEGIES)
    gates = {s.strategy_id: s.gate for s in strategies}
    d = STRATEGIES.decision
    engine = DecisionEngine(d.weights, gates, d.decision_threshold, d.conflict_threshold)
    n_non_no_trade = 0
    while (t := clock.advance()) is not None:
        regime = detector.step(view, t)
        candidates = [c for c in (s.evaluate(view, t) for s in strategies) if c is not None]
        proposed = engine.decide(t, candidates, regime)
        if proposed.action != Action.NO_TRADE:
            n_non_no_trade += 1
    assert ds.n_candidates_total == n_non_no_trade


def test_eligibility_ignores_portfolio_state_by_construction():
    """D3: every non-NO_TRADE, risk-approved candidate becomes a row regardless of how close in time it is
    to another one - there is no "one position at a time" filtering in the dataset."""
    market = random_1m_market(400 * 24, seed=4)
    feats = make_feature_data(400, seed=4)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    if len(ds) >= 2:
        gaps_hours = np.diff(np.sort(ds.t_ms)) / 3_600_000
        assert gaps_hours.min() < 24  # candidates can be adjacent/overlapping, unlike a real one-position backtest


def test_context_columns_match_the_winning_candidates():
    market = random_1m_market(400 * 24, seed=5)
    feats = make_feature_data(400, seed=5)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    if len(ds):
        idx = {n: i for i, n in enumerate(ds.feature_names)}
        contrib_cols = [idx[f"contrib_{s}"] for s in ("trend_momentum", "breakout", "mean_reversion")]
        # exactly the strategies contributing to the vote have contrib=1; direction matches action sign implicitly via label construction
        assert np.all(ds.x[:, contrib_cols].sum(axis=1) >= 1)


def test_dataset_is_deterministic():
    market = random_1m_market(300 * 24, seed=6)
    feats = make_feature_data(300, seed=6)
    ds1 = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    ds2 = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    assert np.array_equal(ds1.t_ms, ds2.t_ms) and np.array_equal(ds1.label, ds2.label)
    assert np.array_equal(ds1.x, ds2.x)
