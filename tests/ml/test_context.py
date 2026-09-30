"""Regression tests for the Stage 6 pre-commit audit's BLOCKER 1 fix: the train/serve feature skew between
``arven.ml.dataset.build_dataset``'s training context and ``arven.ml.filter.build_row``'s live context.
Both now go through the single canonical ``arven.ml.dataset.build_context_vector`` helper.
"""

import inspect

import numpy as np
import pytest
from pipeline_helpers import garbage_features_after, make_feature_data, random_1m_market

from arven.backtest.clock import SimulationClock
from arven.backtest.marketdata import MarketData
from arven.backtest.provider import FeatureView, PortfolioSnapshot
from arven.core.backtest_config import load_backtest_config
from arven.core.config import load_config
from arven.core.ml_config import load_ml_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.strategies_config import load_strategies_config
from arven.core.types import Action
from arven.decision.engine import DecisionEngine
from arven.decision.pipeline import build_strategies
from arven.ml.dataset import CONTEXT_COLUMNS, build_context_vector, build_dataset
from arven.ml.filter import build_row
from arven.regime.detector import RegimeDetector
from arven.risk.engine import RiskEngine

REGIME, STRATEGIES, RISK, BT, ML, APP = (
    load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(),
    load_ml_config(), load_config(),
)
HOUR = 3_600_000


def _first_eligible_proposed(market: MarketData, feats):
    """Replays Stage 5 (as dataset.py does) and returns the first (view, proposed) pair whose action is not
    NO_TRADE - a real ProposedDecision from real regime/strategy/decision-engine state, not a hand-built stub."""
    clock = SimulationClock(feats.t_ms)
    view = FeatureView(feats.t_ms, feats.names, feats.values, clock, feats.first_ready_ms)
    detector = RegimeDetector(REGIME)
    strategies = build_strategies(STRATEGIES)
    gates = {s.strategy_id: s.gate for s in strategies}
    d = STRATEGIES.decision
    engine = DecisionEngine(d.weights, gates, d.decision_threshold, d.conflict_threshold)
    while (t := clock.advance()) is not None:
        regime = detector.step(view, t)
        candidates = [c for c in (s.evaluate(view, t) for s in strategies) if c is not None]
        proposed = engine.decide(t, candidates, regime)
        if proposed.action != Action.NO_TRADE:
            return view, proposed
    return None, None


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_training_row_context_equals_live_row_context_for_the_same_proposed_decision(seed):
    """BLOCKER 1, requirement 5a: for the same ProposedDecision, the training-time context vector
    (build_context_vector, used inside build_dataset) and the live context vector (build_row's context
    portion, used inside MetaFilter.apply) must be identical."""
    market = random_1m_market(300 * 24, seed=seed)
    feats = make_feature_data(300, seed=seed)
    view, proposed = _first_eligible_proposed(market, feats)
    assert proposed is not None, "seed produced no eligible candidate - widen the synthetic window"

    training_ctx = dict(zip(CONTEXT_COLUMNS, build_context_vector(proposed)))
    live_row = build_row(view, proposed, feats.names + CONTEXT_COLUMNS)
    live_ctx = dict(zip(feats.names + CONTEXT_COLUMNS, live_row))
    for col in CONTEXT_COLUMNS:
        assert training_ctx[col] == pytest.approx(live_ctx[col], abs=0, rel=0), col


def test_context_vector_never_uses_risk_engine_bounded_values():
    """The specific bug: dataset.py must not read a risk-engine `signal`'s stop_pct/take_profit_pct into the
    context vector - only `proposed`'s own raw fields. Constructed so RiskEngine's bound (min_stop_pct) would
    visibly change the value if the bug were still present."""
    from arven.decision.engine import ProposedDecision
    from arven.regime.detector import Regime, TrendState, VolState
    from arven.strategies.base import CandidateSignal

    regime = Regime(TrendState.UP, VolState.NORMAL, False, True)
    cand = CandidateSignal("trend_momentum", 1, 0.5, 0.0005, 0.001, 60, ("r",))  # stop below RiskEngine's min_stop_pct
    proposed = ProposedDecision(0, Action.LONG, 0.5, 0.5, ("trend_momentum",), (), (), regime, 0.0005, 0.001, 60, (cand,))

    ctx = dict(zip(CONTEXT_COLUMNS, build_context_vector(proposed)))
    assert ctx["stop_pct"] == 0.0005  # the raw hint, NOT RiskEngine's min_stop_pct-clamped value
    assert ctx["take_profit_pct"] == 0.001


@pytest.mark.parametrize("seed", [1, 4, 9])
def test_full_dataset_perturbation_invariance(seed):
    """BLOCKER 1, requirement 5b (formalizes the audit's ad hoc canary): everything at/after a cut time is
    replaced with fresh Stage-3-plausible garbage on both the 1m market and the feature table. Every dataset
    row with t_ms < cut must be byte-identical to a base run with no perturbation at all - the full
    build_dataset() construction path had no such test before this audit."""
    days = 420
    feats = make_feature_data(days, seed)
    market = random_1m_market(days * 24, seed)
    cut_days = 300
    cut_ms = feats.t_ms[0] + cut_days * 24 * HOUR

    base_ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)

    pert_feats = garbage_features_after(feats, cut_days * 24)
    rng = np.random.default_rng(seed + 500)
    k = int(np.searchsorted(market.time_ms, cut_ms))
    n = len(market.time_ms) - k
    o, h, l, c = market.open.copy(), market.high.copy(), market.low.copy(), market.close.copy()
    base_px = rng.uniform(5_000, 90_000, n)
    op = base_px * (1 + rng.normal(0, 0.01, n))
    cl = base_px * (1 + rng.normal(0, 0.01, n))
    o[k:], c[k:] = op, cl
    h[k:] = np.maximum(op, cl) * (1 + np.abs(rng.normal(0, 0.005, n)))
    l[k:] = np.minimum(op, cl) * (1 - np.abs(rng.normal(0, 0.005, n)))
    fr = market.funding_rate.copy()
    fmask = market.funding_time_ms >= cut_ms
    fr[fmask] = rng.normal(0, 0.002, int(fmask.sum()))
    pert_market = MarketData(market.time_ms, o, h, l, c, market.window_start_ms, market.window_end_ms,
                              market.funding_time_ms, fr, market.funding_interval_ms)

    pert_ds = build_dataset(pert_market, pert_feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)

    base_before = [i for i in range(len(base_ds)) if base_ds.t_ms[i] < cut_ms]
    pert_before = [i for i in range(len(pert_ds)) if pert_ds.t_ms[i] < cut_ms]
    assert len(base_before) > 20, "widen the window - too few rows before the cut to be a meaningful check"

    assert list(base_ds.t_ms[base_before]) == list(pert_ds.t_ms[pert_before])
    assert list(base_ds.label[base_before]) == list(pert_ds.label[pert_before])
    assert np.array_equal(base_ds.net_return[base_before], pert_ds.net_return[pert_before])
    assert np.array_equal(base_ds.x[base_before], pert_ds.x[pert_before])


def test_context_vector_takes_no_portfolio_argument():
    """BLOCKER 1, requirement 5c: build_context_vector's signature structurally cannot read portfolio
    state - it takes only a ProposedDecision, which itself carries no portfolio field (the decision engine
    is portfolio-blind by Stage 5 design; this just confirms the context builder inherits that)."""
    sig = inspect.signature(build_context_vector)
    assert list(sig.parameters) == ["proposed"]
    from arven.decision.engine import ProposedDecision

    field_names = {f for f in ProposedDecision.__dataclass_fields__}
    assert not any("portfolio" in f.lower() or "equity" in f.lower() or "wallet" in f.lower() for f in field_names)
