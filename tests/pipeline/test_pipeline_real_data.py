"""Stage 5 pipeline on the real database and feature cache (opt-in; development period only, read-only).

Run with: ``ARVEN_REAL_DATA_TESTS=1 .venv/Scripts/python.exe -m pytest tests/pipeline/test_real_data.py``
"""

import os

import pytest

from arven.backtest.report import result_hash
from arven.core.backtest_config import load_backtest_config
from arven.core.config import load_config
from arven.core.features_config import load_features_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.splitguard import BacktestPeriod, SealedAccessError
from arven.core.strategies_config import load_strategies_config
from arven.decision.pipeline import Stage5Pipeline
from arven.runs import execute_run, load_inputs, make_guard

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def real_setup():
    if os.environ.get("ARVEN_REAL_DATA_TESTS") != "1":
        pytest.skip("set ARVEN_REAL_DATA_TESTS=1 to run real-data checks")
    cfg = load_config()
    if not cfg.data.database_path.exists():
        pytest.skip("no local database")
    return cfg


def make_pipe(bt):
    return Stage5Pipeline(load_regime_config(), load_strategies_config(), load_risk_config(), bt)


def test_pipeline_runs_on_the_real_development_period_and_reproduces(real_setup, tmp_path):
    cfg = real_setup
    bt, fcfg = load_backtest_config(), load_features_config()
    window = make_guard(cfg).resolve(BacktestPeriod.DEVELOPMENT)
    inputs = load_inputs(cfg, fcfg, window)

    out1 = execute_run(cfg, bt, fcfg, window, make_pipe(bt), inputs, out_dir=tmp_path)
    out2 = execute_run(cfg, bt, fcfg, window, make_pipe(bt), inputs, out_dir=tmp_path)
    assert out1.result_hash == out2.result_hash == result_hash(out1.result)
    assert out1.manifest["period"] == "development" and out1.manifest["touched_test_set"] is False
    assert out1.manifest["feature_version"] == "v1"


def test_sealed_test_period_is_refused_for_the_pipeline_without_acknowledgement(real_setup):
    cfg = real_setup
    with pytest.raises(SealedAccessError):
        make_guard(cfg).resolve(BacktestPeriod.TEST)


def test_validation_period_is_allowed_and_not_marked_touched(real_setup, tmp_path):
    cfg = real_setup
    bt, fcfg = load_backtest_config(), load_features_config()
    window = make_guard(cfg).resolve(BacktestPeriod.VALIDATION)
    inputs = load_inputs(cfg, fcfg, window)
    out = execute_run(cfg, bt, fcfg, window, make_pipe(bt), inputs, out_dir=tmp_path)
    assert out.manifest["touched_test_set"] is False and out.manifest["period"] == "validation"


def test_development_run_reads_no_data_at_or_after_its_own_end(real_setup, tmp_path):
    cfg = real_setup
    bt, fcfg = load_backtest_config(), load_features_config()
    window = make_guard(cfg).resolve(BacktestPeriod.DEVELOPMENT)
    inputs = load_inputs(cfg, fcfg, window)
    for r in inputs.data_ranges:
        assert r["end_ms"] <= window.end_ms
    assert int(inputs.market.time_ms[-1]) < window.end_ms
