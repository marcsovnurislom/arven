"""Stage 6 end-to-end on the real database and Stage 3 feature cache (opt-in; development+validation only,
read-only, never test). Mirrors the Stage 3/4/5 real-data test pattern exactly.

Run with: ``ARVEN_REAL_DATA_TESTS=1 .venv/Scripts/python.exe -m pytest tests/ml/test_ml_real_data.py``
"""

import os

import pytest

from arven.core.backtest_config import load_backtest_config
from arven.core.config import load_config
from arven.core.features_config import load_features_config
from arven.core.ml_config import load_ml_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.splitguard import BacktestPeriod, SealedAccessError
from arven.core.strategies_config import load_strategies_config
from arven.ml.artifact import verify_artifact
from arven.ml_runs import InsufficientDataError, make_guard, train_and_save

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def real_setup():
    if os.environ.get("ARVEN_REAL_DATA_TESTS") != "1":
        pytest.skip("set ARVEN_REAL_DATA_TESTS=1 to run real-data checks")
    cfg = load_config()
    if not cfg.data.database_path.exists():
        pytest.skip("no local database")
    return cfg, load_ml_config(), load_features_config(), load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config()


@pytest.mark.parametrize("model_family", ["logistic", "lightgbm"])
def test_train_and_save_on_real_development_and_validation_data(real_setup, tmp_path, model_family):
    app, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt_cfg = real_setup
    try:
        out = train_and_save(app, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt_cfg, model_family, out_dir=tmp_path)
    except InsufficientDataError as e:
        pytest.skip(f"not enough real eligible candidates to train on: {e}")

    m = out.manifest
    assert m["touched_test_set"] is False
    assert m["training_period_start_ms"] < m["validation_period_start_ms"] < m["validation_period_end_ms"]
    assert m["feature_version"] == "v1"
    assert m["n_train_rows"] > 0 and m["n_calibration_rows"] > 0
    res = verify_artifact(out.model_dir)
    assert res["ok"], res["problems"]


@pytest.mark.parametrize("model_family", ["logistic", "lightgbm"])
def test_training_is_deterministic_on_real_data(real_setup, tmp_path, model_family):
    app, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt_cfg = real_setup
    try:
        out1 = train_and_save(app, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt_cfg, model_family, out_dir=tmp_path)
        out2 = train_and_save(app, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt_cfg, model_family, out_dir=tmp_path)
    except InsufficientDataError as e:
        pytest.skip(f"not enough real eligible candidates to train on: {e}")
    assert out1.manifest["model_artifact_hash"] == out2.manifest["model_artifact_hash"]
    assert out1.manifest["training_dataset_fingerprint"] == out2.manifest["training_dataset_fingerprint"]


def test_sealed_test_period_is_never_touched_by_the_ml_split_guard(real_setup):
    app = real_setup[0]
    with pytest.raises(SealedAccessError):
        make_guard(app).resolve(BacktestPeriod.TEST)


def test_real_eligible_candidate_counts_are_reported_honestly(real_setup, tmp_path):
    """Whatever the real number is, train_and_save either trains on it or raises InsufficientDataError with
    the exact counts - it never silently proceeds with a degenerate fit."""
    app, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt_cfg = real_setup
    try:
        out = train_and_save(app, ml_cfg, fcfg, regime_cfg, strategies_cfg, risk_cfg, bt_cfg, "logistic", out_dir=tmp_path)
        assert out.manifest["n_candidates_total"] >= out.manifest["n_train_rows"] + out.manifest["n_calibration_rows"]
    except InsufficientDataError as e:
        assert e.n_eligible < 20 and e.n_candidates_total >= e.n_eligible
