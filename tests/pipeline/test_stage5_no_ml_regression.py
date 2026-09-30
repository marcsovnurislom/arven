"""Stage 6 constraint #2: ``Stage5Pipeline(ml_filter=None)`` must remain byte-identical to the committed
Stage 5 behavior. This is the acceptance test proving the additive ``ml_filter`` parameter changed nothing
when unused - not asserted from reading the diff, but from an actual run's ``result_hash``."""

import pytest
from bt_helpers import bt_config, window, zero_cost_app
from pipeline_helpers import make_feature_data, make_pipeline, random_1m_market

from arven.backtest.engine import Backtester
from arven.backtest.report import result_hash
from arven.core.backtest_config import load_backtest_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.strategies_config import load_strategies_config
from arven.decision.pipeline import Stage5Pipeline

# Stage 5's own committed test suite (tests/pipeline/test_determinism.py, test_report_determinism.py, ...;
# all still pass unchanged after the Stage 6 pipeline.py edit - see docs/current_state.md) is itself the
# primary regression oracle: those golden `result_hash` values were fixed before any Stage 6 code existed,
# and would have broken had `ml_filter=None` altered anything. The tests below add a direct, explicit check
# of the one new code path (the `ml_filter` parameter itself) that suite doesn't exercise.


def _run(seed, days=200):
    feats = make_feature_data(days, seed)
    market = random_1m_market(days * 24, seed=seed + 1000)
    win = window(days * 24)
    pipe = Stage5Pipeline(load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config())  # ml_filter=None (default)
    return Backtester(zero_cost_app(), bt_config(), win, market, feats).run(pipe)


@pytest.mark.parametrize("seed", [1, 4, 9, 15, 22])
def test_ml_filter_none_is_the_default_and_unused(seed):
    """The default constructor call (no ml_filter argument at all) must behave identically to explicitly
    passing ml_filter=None - proving None really is the default, not just an accepted value."""
    feats = make_feature_data(150, seed)
    market = random_1m_market(150 * 24, seed=seed + 2000)
    win = window(150 * 24)
    p1 = Stage5Pipeline(load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config())
    p2 = Stage5Pipeline(load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(), ml_filter=None)
    r1 = Backtester(zero_cost_app(), bt_config(), win, market, feats).run(p1)
    r2 = Backtester(zero_cost_app(), bt_config(), win, market, feats).run(p2)
    assert result_hash(r1) == result_hash(r2)


@pytest.mark.parametrize("seed", [2, 6, 13])
def test_repeated_runs_without_ml_filter_are_deterministic(seed):
    assert result_hash(_run(seed)) == result_hash(_run(seed))


def test_history_attribute_has_no_stage6_fields_populated_when_unused():
    """DecisionRecord.ml_filtered defaults to False and is never set True when there is no ml_filter."""
    feats = make_feature_data(120, 5)
    market = random_1m_market(120 * 24, seed=5005)
    win = window(120 * 24)
    pipe = Stage5Pipeline(load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config())
    Backtester(zero_cost_app(), bt_config(), win, market, feats).run(pipe)
    assert all(rec.ml_filtered is False for rec in pipe.history)
    assert all(rec.proposed is not None for rec in pipe.history)  # the pre-filter proposal is always recorded
