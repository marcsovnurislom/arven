"""Determinism and reproducibility of the full Stage 5 pipeline through the real Stage 4 engine."""

import pytest
from bt_helpers import bt_config, make_market as bt_make_market, window, zero_cost_app
from pipeline_helpers import make_feature_data, make_pipeline, run_pipeline

from arven.backtest.engine import Backtester
from arven.backtest.report import result_hash


@pytest.mark.parametrize("seed", [2, 6, 13])
def test_two_independent_runs_give_an_identical_result_hash(seed):
    res1, _, _ = run_pipeline(200, seed=seed)
    res2, _, _ = run_pipeline(200, seed=seed)
    assert result_hash(res1) == result_hash(res2)
    assert res1.final_wallet == res2.final_wallet
    assert len(res1.trades) == len(res2.trades)


def test_result_is_independent_of_a_second_unrelated_pipeline_instance_in_the_same_process():
    """Building and running a second, throwaway pipeline first must not perturb a later run: there is no
    shared mutable global state between Stage5Pipeline instances."""
    feats = make_feature_data(150, seed=8)
    market = bt_make_market(150 * 24)
    win = window(150 * 24)

    _ = Backtester(zero_cost_app(), bt_config(), win, market, feats).run(make_pipeline())  # throwaway
    a = Backtester(zero_cost_app(), bt_config(), win, market, feats).run(make_pipeline())
    b = Backtester(zero_cost_app(), bt_config(), win, market, feats).run(make_pipeline())
    assert result_hash(a) == result_hash(b)


def test_running_the_same_pipeline_object_twice_gives_the_same_result():
    """Backtester.run(provider) calls provider.prepare() each time: reusing one Stage5Pipeline object for
    two runs must not leak state from the first run into the second (regime dwell counters, risk circuit
    breakers, ...)."""
    feats = make_feature_data(180, seed=11)
    market = bt_make_market(180 * 24)
    win = window(180 * 24)
    pipe = make_pipeline()
    r1 = Backtester(zero_cost_app(), bt_config(), win, market, feats).run(pipe)
    r2 = Backtester(zero_cost_app(), bt_config(), win, market, feats).run(pipe)
    assert result_hash(r1) == result_hash(r2)


def test_stress_flag_changes_the_result_deterministically():
    res_normal, _, _ = run_pipeline(200, seed=4, stress=False)
    res_stress, _, _ = run_pipeline(200, seed=4, stress=True)
    if res_normal.trades:  # only meaningful if the scenario actually traded
        assert result_hash(res_normal) != result_hash(res_stress)
    res_stress2, _, _ = run_pipeline(200, seed=4, stress=True)
    assert result_hash(res_stress) == result_hash(res_stress2)


def test_decision_history_is_also_reproducible():
    """Not just the ledgers: the full explanation trail (candidates, regime, risk reasons) reproduces too."""
    _, pipe1, _ = run_pipeline(150, seed=7)
    _, pipe2, _ = run_pipeline(150, seed=7)
    h1 = [(r.t_ms, r.regime.label, r.proposed.action.value, r.risk.outcome, r.risk.reason) for r in pipe1.history]
    h2 = [(r.t_ms, r.regime.label, r.proposed.action.value, r.risk.outcome, r.risk.reason) for r in pipe2.history]
    assert h1 == h2


def test_config_hash_in_describe_changes_when_a_parameter_changes():
    from arven.core.strategies_config import load_strategies_config

    base = load_strategies_config()
    changed = base.model_copy(update={"decision": base.decision.model_copy(update={"decision_threshold": 0.99})})
    p1, p2 = make_pipeline(), make_pipeline(strategies_cfg=changed)
    assert p1.describe()["strategies_config_hash"] != p2.describe()["strategies_config_hash"]
    assert p1.describe()["regime_config_hash"] == p2.describe()["regime_config_hash"]  # unaffected
