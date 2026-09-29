"""Decision engine: regime gating, weighted vote, conflict rule, threshold, confidence."""

import pytest

from arven.core.types import Action
from arven.decision.engine import DecisionEngine
from arven.regime.detector import Regime, TrendState, VolState
from arven.strategies.base import CandidateSignal

TREND_UP = Regime(TrendState.UP, VolState.NORMAL, False, True)
NO_TREND = Regime(TrendState.NONE, VolState.NORMAL, False, True)
HIGH_VOL_STRESS = Regime(TrendState.NONE, VolState.HIGH, True, True)


def cand(strategy_id, direction, strength, reasons=("r",)):
    return CandidateSignal(strategy_id, direction, strength, 0.02, 0.04, 60, reasons)


class Gate:
    def __init__(self, allowed_trends=None, allowed_vols=None, require_not_stress=False):
        self.allowed_trends, self.allowed_vols, self.require_not_stress = allowed_trends, allowed_vols, require_not_stress


def engine(weights=None, gates=None, threshold=0.3, conflict=0.5):
    weights = weights or {"a": 1.0, "b": 1.0, "c": 1.0}
    gates = gates or {k: Gate() for k in weights}
    return DecisionEngine(weights, gates, threshold, conflict)


def test_single_candidate_above_threshold_wins():
    d = engine().decide(1000, [cand("a", 1, 0.6)], TREND_UP)
    assert d.action == Action.LONG and d.contributing == ("a",) and d.score == pytest.approx(0.6)
    assert d.stop_pct == pytest.approx(0.02) and d.take_profit_pct == pytest.approx(0.04)
    assert d.max_holding_minutes == 60


def test_no_candidates_is_no_trade():
    d = engine().decide(1000, [], TREND_UP)
    assert d.action == Action.NO_TRADE and d.score == 0.0 and d.confidence == 0.0


def test_below_threshold_is_no_trade():
    d = engine(threshold=0.9).decide(1000, [cand("a", 1, 0.5)], TREND_UP)
    assert d.action == Action.NO_TRADE


def test_agreeing_candidates_add_weighted_strength():
    d = engine().decide(1000, [cand("a", 1, 0.4), cand("b", 1, 0.5)], TREND_UP)
    assert d.action == Action.LONG and d.score == pytest.approx(0.9)
    assert set(d.contributing) == {"a", "b"}


def test_opposing_candidates_partially_cancel():
    d = engine().decide(1000, [cand("a", 1, 0.6), cand("b", -1, 0.2)], TREND_UP)
    assert d.action == Action.LONG and d.score == pytest.approx(0.4)
    assert d.contributing == ("a",)  # only the winning side contributes


def test_conflict_rule_forces_no_trade_when_both_sides_are_strong():
    d = engine(conflict=0.5).decide(1000, [cand("a", 1, 0.6), cand("b", -1, 0.6)], TREND_UP)
    assert d.action == Action.NO_TRADE and "conflict" in d.reasons[0]


def test_weights_scale_contribution():
    w = {"a": 2.0, "b": 1.0, "c": 1.0}
    d = engine(weights=w).decide(1000, [cand("a", 1, 0.3)], TREND_UP)
    assert d.score == pytest.approx(0.6)


def test_regime_gating_filters_out_disallowed_candidates():
    gates = {"a": Gate(allowed_trends=("TREND_UP",)), "b": Gate()}
    e = engine(weights={"a": 1.0, "b": 1.0}, gates=gates)
    d = e.decide(1000, [cand("a", 1, 0.6)], NO_TREND)  # "a" not allowed in NO_TREND
    assert d.action == Action.NO_TRADE and d.gated_out == ("a",)


def test_regime_gating_by_volatility_and_stress():
    gates = {"a": Gate(allowed_vols=("LOW",)), "b": Gate(require_not_stress=True)}
    e = engine(weights={"a": 1.0, "b": 1.0}, gates=gates)
    d = e.decide(1000, [cand("a", 1, 0.9), cand("b", 1, 0.9)], HIGH_VOL_STRESS)
    assert d.action == Action.NO_TRADE
    assert set(d.gated_out) == {"a", "b"}


def test_allowed_trends_none_means_any_regime():
    gates = {"a": Gate(allowed_trends=None)}
    d = engine(weights={"a": 1.0}, gates=gates).decide(1000, [cand("a", 1, 0.9)], NO_TREND)
    assert d.action == Action.LONG


def test_stop_and_target_are_weighted_averages_of_winners_only():
    losers_and_winners = [
        CandidateSignal("a", 1, 0.5, 0.01, 0.02, 30, ("ra",)),
        CandidateSignal("b", 1, 0.5, 0.03, 0.06, 90, ("rb",)),
        CandidateSignal("c", -1, 0.9, 0.10, 0.20, 10, ("rc",)),  # opposite side and gated out below anyway
    ]
    gates = {"a": Gate(), "b": Gate(), "c": Gate(allowed_trends=("TREND_DOWN",))}
    d = engine(weights={"a": 1.0, "b": 1.0, "c": 1.0}, gates=gates, conflict=2.0).decide(1000, losers_and_winners, TREND_UP)
    assert d.action == Action.LONG
    assert d.stop_pct == pytest.approx(0.02)  # equal weights (0.5*0.5 each): mean of 0.01 and 0.03
    assert d.take_profit_pct == pytest.approx(0.04)
    assert d.max_holding_minutes == 30  # the most conservative (shortest) of the winners' holding caps


def test_confidence_is_score_over_total_weight_and_bounded():
    d = engine(weights={"a": 1.0, "b": 1.0, "c": 1.0}, threshold=0.01).decide(1000, [cand("a", 1, 1.0), cand("b", 1, 1.0), cand("c", 1, 1.0)], TREND_UP)
    assert d.confidence == pytest.approx(1.0)
    d2 = engine(threshold=0.01).decide(1000, [cand("a", 1, 0.5)], TREND_UP)
    assert d2.confidence == pytest.approx(0.5 / 3)


def test_reasons_come_only_from_winning_candidates():
    d = engine().decide(1000, [cand("a", 1, 0.6, reasons=("only-a",)), cand("b", -1, 0.1, reasons=("only-b",))], TREND_UP)
    assert all("only-a" in r for r in d.reasons)
    assert not any("only-b" in r for r in d.reasons)


def test_all_candidates_are_preserved_for_logging_even_when_gated_or_losing():
    gates = {"a": Gate(), "b": Gate(allowed_trends=("TREND_DOWN",))}
    d = engine(weights={"a": 1.0, "b": 1.0}, gates=gates).decide(1000, [cand("a", 1, 0.6), cand("b", -1, 0.9)], TREND_UP)
    assert len(d.all_candidates) == 2
    assert d.action == Action.LONG  # b was gated out, so only a counts
