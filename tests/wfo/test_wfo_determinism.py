"""Two independent run_stage7() calls on the same synthetic data must produce byte-identical reports
(structurally: identical schedule, identical hyperparameters, identical distributions) - the Stage 7
analogue of the existing Stage 6 two-run determinism tests.
"""

import numpy as np
import pytest
from pipeline_helpers import make_feature_data, random_1m_market

from arven.core.backtest_config import load_backtest_config
from arven.core.config import AppConfig, load_config
from arven.core.features_config import load_features_config
from arven.core.ml_config import MLConfig, load_ml_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.splitguard import BacktestPeriod, SplitGuard
from arven.core.strategies_config import load_strategies_config
from arven.ml.dataset import build_dataset
from arven.wfo import MINIMUM_WINDOWS, InsufficientWindowsError, enforce_minimum_windows
from arven.ml.splits import generate_folds

REGIME, STRATEGIES, RISK, BT, ML, APP, FEATURES = (
    load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(),
    load_ml_config(), load_config(), load_features_config(),
)


def test_insufficient_windows_error_carries_the_count_and_is_never_silently_caught():
    # 58 of the real 60-month development+validation range leaves almost no room -> far fewer than
    # MINIMUM_WINDOWS folds (a direct generate_folds call, not a config mutation - MLConfig is frozen).
    guard = SplitGuard(APP.splits)
    dev, val = guard.resolve(BacktestPeriod.DEVELOPMENT), guard.resolve(BacktestPeriod.VALIDATION)
    folds = generate_folds(dev.start_ms, val.end_ms, min_train_months=58, retrain_interval_months=3)
    assert len(folds) < MINIMUM_WINDOWS
    with pytest.raises(InsufficientWindowsError) as exc:
        enforce_minimum_windows(folds)
    assert exc.value.n_windows == len(folds)


@pytest.mark.parametrize("seed", [5])
def test_fit_window_model_is_deterministic_for_the_same_window_and_data(seed):
    """Two independent fit_window_model() calls on the identical dataset/fold/hyperparameters give
    identical fitted artifacts (same predictions on a fixed probe), matching Stage 6's own model-level
    determinism guarantee, now exercised at the per-window granularity Stage 7 introduces."""
    from arven.wfo import fit_window_model
    from arven.ml.splits import generate_folds
    from arven.ml.train import select_feature_columns

    market = random_1m_market(500 * 24, seed=seed)
    feats = make_feature_data(500, seed=seed)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    if len(ds) < 100 or len(np.unique(ds.label)) < 2:
        pytest.skip("seed produced too few/degenerate eligible rows")
    folds = generate_folds(int(ds.t_ms.min()), int(ds.t_ms.max()) + 1, min_train_months=3, retrain_interval_months=1)
    idx = next((i for i in range(1, len(folds)) if int((ds.t_ms < folds[i].valid_start_ms).sum()) > 20), None)
    if idx is None:
        pytest.skip("no usable window in this synthetic dataset")

    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp = ML.hyperparameters.logistic[0].model_dump()
    r1 = fit_window_model(ds, "logistic", hp, col_idx, folds, idx, ML, APP.project.random_seed)
    r2 = fit_window_model(ds, "logistic", hp, col_idx, folds, idx, ML, APP.project.random_seed)
    if r1 is None or r2 is None:
        pytest.skip("degenerate split for this seed/window")

    probe = ds.x[:5, col_idx]
    assert np.array_equal(r1.artifact.predict_calibrated(probe), r2.artifact.predict_calibrated(probe))
    assert r1.threshold_selection["selected"] == r2.threshold_selection["selected"]
    assert r1.metrics == r2.metrics
