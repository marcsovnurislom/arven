"""MetaFilter: may only pass or veto, never create/flip/resize. Property tests over many random decisions."""

import dataclasses

import numpy as np
import pytest
from stage5_helpers import HOUR_MS, T0, single_row

from arven.core.types import Action
from arven.ml.artifact import ModelArtifact
from arven.ml.calibration import IsotonicCalibrator
from arven.ml.dataset import CONTEXT_COLUMNS
from arven.ml.filter import MetaFilter, RandomFilter, build_row
from arven.regime.detector import Regime, TrendState, VolState
from arven.strategies.base import CandidateSignal


class ConstantModel:
    """A stub raw-score model: always returns the same probability, for controllable filter tests."""

    def __init__(self, p: float):
        self.p = p

    def predict_proba(self, x):
        return np.full(len(x), self.p)


def make_artifact(p: float, threshold: float, feature_names) -> ModelArtifact:
    model = ConstantModel(p)
    calibrator = IsotonicCalibrator(np.array([0.0, 1.0]), np.array([p, p]))  # identity-ish, always -> p
    # model_family="lightgbm": ConstantModel ignores its input either way, and this sidesteps the
    # logistic-only standardisation path (irrelevant to what these tests check).
    return ModelArtifact("lightgbm", model, calibrator, feature_names, threshold, None, None)


def make_proposed(hour_index, action=Action.LONG, score=0.6, contributing=("trend_momentum",), regime=None):
    regime = regime or Regime(TrendState.UP, VolState.NORMAL, False, True)
    cand = CandidateSignal("trend_momentum", 1, 0.6, 0.02, 0.04, 60, ("r",))
    from arven.decision.engine import ProposedDecision

    t_ms = T0 + hour_index * HOUR_MS
    return ProposedDecision(t_ms, action, score, 0.5, contributing, (), ("r",), regime, 0.02, 0.04, 60, (cand,))


def feature_view_for(proposed, overrides=None):
    row = dict(overrides or {})
    view, t = single_row(row, start_ms=proposed.t_ms)
    assert t == proposed.t_ms
    return view


@pytest.mark.parametrize("p,threshold,expect_pass", [(0.9, 0.55, True), (0.55, 0.55, True), (0.54, 0.55, False), (0.1, 0.55, False)])
def test_pass_or_veto_boundary(p, threshold, expect_pass):
    feature_names = tuple(f"h1_ret_1,".rstrip(",") for _ in [0]) + CONTEXT_COLUMNS  # a single stage3 col + context
    artifact = make_artifact(p, threshold, feature_names)
    mf = MetaFilter(artifact, "test-model")
    proposed = make_proposed(0)
    view = feature_view_for(proposed, {"h1_ret_1": 0.0})
    out = mf.apply(proposed, view)
    if expect_pass:
        assert out is proposed or out == proposed
        assert out.action == Action.LONG
    else:
        assert out.action == Action.NO_TRADE


def test_no_trade_proposal_passes_through_untouched_without_calling_the_model():
    feature_names = ("h1_ret_1",) + CONTEXT_COLUMNS
    artifact = make_artifact(0.0, 0.55, feature_names)  # would veto everything if called
    mf = MetaFilter(artifact, "m")
    from arven.decision.engine import ProposedDecision

    no_trade = ProposedDecision(T0, Action.NO_TRADE, 0.0, 0.0, (), (), ("x",), Regime(TrendState.NONE, VolState.NORMAL, False, True), None, None, None, ())
    out = mf.apply(no_trade, feature_view_for(no_trade, {"h1_ret_1": 0.0}))
    assert out is no_trade
    assert mf.n_seen == 0


def test_veto_never_flips_direction_or_changes_sizing_hints():
    feature_names = ("h1_ret_1",) + CONTEXT_COLUMNS
    artifact = make_artifact(0.0, 0.55, feature_names)
    mf = MetaFilter(artifact, "m")
    proposed = make_proposed(0, action=Action.SHORT, contributing=("mean_reversion",))
    out = mf.apply(proposed, feature_view_for(proposed, {"h1_ret_1": 0.0}))
    assert out.action == Action.NO_TRADE  # downgraded, never LONG (never flipped)
    assert out.stop_pct is None and out.take_profit_pct is None and out.max_holding_minutes is None
    assert out.contributing == ()
    assert out.score == proposed.score and out.regime == proposed.regime  # everything else preserved for the record


@pytest.mark.parametrize("seed", range(30))
def test_property_never_upgrades_never_flips_never_resizes(seed):
    rng = np.random.default_rng(seed)
    feature_names = ("h1_ret_1",) + CONTEXT_COLUMNS
    p = float(rng.random())
    threshold = float(rng.uniform(0.1, 0.9))
    artifact = make_artifact(p, threshold, feature_names)
    mf = MetaFilter(artifact, "m")
    action = Action.LONG if rng.random() < 0.5 else Action.SHORT
    proposed = make_proposed(int(rng.integers(0, 1_000_000)), action=action, score=float(rng.uniform(-1, 1)))
    out = mf.apply(proposed, feature_view_for(proposed, {"h1_ret_1": 0.0}))
    assert out.action in (proposed.action, Action.NO_TRADE)  # never a different non-NO_TRADE action
    if out.action == Action.NO_TRADE and proposed.action != Action.NO_TRADE:
        assert out.stop_pct is None and out.take_profit_pct is None and out.contributing == ()
    else:
        assert out.stop_pct == proposed.stop_pct and out.take_profit_pct == proposed.take_profit_pct


def test_random_filter_control_rejects_approximately_the_configured_rate():
    feature_names = ("h1_ret_1",) + CONTEXT_COLUMNS
    rf = RandomFilter(reject_rate=0.7, seed=42)
    n = 2000
    passed = 0
    for i in range(n):
        proposed = make_proposed(i)
        out = rf.apply(proposed, feature_view_for(proposed, {"h1_ret_1": 0.0}))
        passed += out.action != Action.NO_TRADE
    assert abs(passed / n - 0.3) < 0.03


def test_random_filter_is_deterministic_given_the_same_seed():
    def run(seed):
        rf = RandomFilter(0.5, seed=seed)
        out = []
        for i in range(50):
            proposed = make_proposed(i)
            out.append(rf.apply(proposed, feature_view_for(proposed, {"h1_ret_1": 0.0})).action)
        return out

    assert run(7) == run(7)


def test_random_filter_rejects_invalid_rate():
    with pytest.raises(ValueError):
        RandomFilter(1.5, seed=1)


def test_build_row_matches_feature_names_order():
    feature_names = ("h1_ret_1", "h1_rsi") + CONTEXT_COLUMNS
    proposed = make_proposed(0)
    view = feature_view_for(proposed, {"h1_ret_1": 0.01, "h1_rsi": 55.0})
    row = build_row(view, proposed, feature_names)
    assert row.shape == (len(feature_names),)
    assert row[0] == pytest.approx(0.01) and row[1] == pytest.approx(55.0)
