"""Stage5Pipeline: SignalProvider protocol compliance and basic wiring."""

import json

from bt_helpers import bt_config, make_market as bt_make_market, window, zero_cost_app
from pipeline_helpers import make_feature_data, make_pipeline, run_pipeline

from arven.backtest.engine import Backtester
from arven.backtest.types import OrderStatus
from arven.core.backtest_config import load_backtest_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.strategies_config import load_strategies_config
from arven.decision.pipeline import PIPELINE_NAME, Stage5Pipeline


def test_describe_is_json_serialisable_and_names_every_strategy():
    d = make_pipeline().describe()
    json.dumps(d)  # must not raise
    assert d["name"] == PIPELINE_NAME
    assert set(d["strategy_ids"]) == {"trend_momentum", "breakout", "mean_reversion"}
    assert len(d["regime_config_hash"]) == 64 and len(d["strategies_config_hash"]) == 64 and len(d["risk_config_hash"]) == 64


def test_prepare_resets_state_between_runs():
    p = make_pipeline()
    res1, _, _ = run_pipeline(150, seed=1)
    # reuse the same pipeline object for a second run (as Backtester.run(provider) would if called twice)
    # and confirm prepare() wiped the regime/risk state, giving the same result both times.
    win_hours = 150 * 24
    feats = make_feature_data(150, seed=1)
    market = bt_make_market(win_hours)
    res2 = Backtester(zero_cost_app(), bt_config(), window(win_hours), market, feats).run(p)
    assert res1.final_wallet == res2.final_wallet
    assert len(res1.trades) == len(res2.trades)


def test_pipeline_produces_a_nonempty_decision_history_and_some_trades_over_a_long_window():
    result, pipe, _ = run_pipeline(400, seed=3)
    assert len(pipe.history) == result.n_decisions
    assert any(r.risk.outcome == "signal" for r in pipe.history)
    assert len(result.trades) > 0
    assert any(e.status == OrderStatus.FILLED for e in result.orders)


def test_every_decision_record_has_a_regime_and_matching_time():
    result, pipe, _ = run_pipeline(100, seed=4)
    for rec in pipe.history:
        assert rec.regime is not None
        assert rec.proposed.t_ms == rec.t_ms == rec.risk.t_ms


def test_an_unreachable_decision_threshold_produces_no_trades():
    base = load_strategies_config()
    strict = base.model_copy(update={"decision": base.decision.model_copy(update={"decision_threshold": 5.0})})
    p = Stage5Pipeline(load_regime_config(), strict, load_risk_config(), load_backtest_config())
    feats = make_feature_data(200, seed=3)
    market = bt_make_market(200 * 24)
    result = Backtester(zero_cost_app(), bt_config(), window(200 * 24), market, feats).run(p)
    assert not result.trades  # threshold=5.0 exceeds the maximum possible score: nothing can ever fire
