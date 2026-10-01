"""fit_window_model: purge/embargo reuse (not a naive boundary split), degenerate-split handling, and
shuffle_dataset_labels - using synthetic data so these run fast and deterministically.
"""

import numpy as np
import pytest
from pipeline_helpers import make_feature_data, random_1m_market

from arven.core.backtest_config import load_backtest_config
from arven.core.config import load_config
from arven.core.features_config import load_features_config
from arven.core.ml_config import load_ml_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.strategies_config import load_strategies_config
from arven.ml.dataset import build_dataset
from arven.ml.splits import Fold, generate_folds, purge_and_embargo_train_mask, validation_mask
from arven.ml.train import select_feature_columns
from arven.wfo import estimate_matched_reject_rate, fit_window_model, shuffle_dataset_labels

REGIME, STRATEGIES, RISK, BT, ML, APP, FEATURES = (
    load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(),
    load_ml_config(), load_config(), load_features_config(),
)


def _real_dataset(seed, days=500):
    market = random_1m_market(days * 24, seed=seed)
    feats = make_feature_data(days, seed=seed)
    return build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)


def test_shuffle_dataset_labels_permutes_only_the_label_column():
    ds = _real_dataset(seed=1)
    if len(ds) < 20:
        pytest.skip("seed produced too few rows")
    shuffled = shuffle_dataset_labels(ds, seed=7)
    assert np.array_equal(shuffled.t_ms, ds.t_ms)
    assert np.array_equal(shuffled.x, ds.x)
    assert np.array_equal(shuffled.horizon_ms, ds.horizon_ms)
    assert sorted(shuffled.label.tolist()) == sorted(ds.label.tolist())  # same multiset
    if len(np.unique(ds.label)) == 2 and len(ds) > 5:
        assert not np.array_equal(shuffled.label, ds.label)  # overwhelmingly likely to actually differ


def test_shuffle_dataset_labels_is_deterministic_for_a_fixed_seed():
    ds = _real_dataset(seed=2)
    if len(ds) < 20:
        pytest.skip("seed produced too few rows")
    a = shuffle_dataset_labels(ds, seed=11)
    b = shuffle_dataset_labels(ds, seed=11)
    assert np.array_equal(a.label, b.label)


def test_fit_window_model_training_rows_are_exactly_the_purge_embargo_mask_minus_the_calibration_block():
    """The specific bugs this function exists to avoid: (a) using dataset.t_ms < fold.valid_start_ms
    directly (train_final_model's boundary split) instead of purge_and_embargo_train_mask would include
    rows whose label horizon reaches into the window; (b) calibrating on the window's OWN rows instead of
    prior folds' rows would be circular (fixed 2026-10-01 - see BLOCKER: causal hyperparameter/calibration
    audit). fit_window_model must use exactly purge_and_embargo_mask(fold i) MINUS the union of
    validation_mask over the last CALIBRATION_LOOKBACK_FOLDS folds before i, and calibrate on that union
    (widened from a single preceding fold on 2026-10-01 - small-sample isotonic instability, see docstring)."""
    from arven.wfo import CALIBRATION_LOOKBACK_FOLDS

    ds = _real_dataset(seed=3, days=800)
    if len(ds) < 100:
        pytest.skip("seed produced too few rows")
    folds = generate_folds(int(ds.t_ms.min()), int(ds.t_ms.max()) + 1, min_train_months=3, retrain_interval_months=1)
    idx = next((i for i in range(1, len(folds)) if int((ds.t_ms < folds[i].valid_start_ms).sum()) > 40), None)
    if idx is None:
        pytest.skip("no usable window in this synthetic dataset")
    fold = folds[idx]
    calib_folds = folds[max(0, idx - CALIBRATION_LOOKBACK_FOLDS):idx]

    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    naive_mask = ds.t_ms < fold.valid_start_ms
    calib_mask = np.zeros(len(ds.t_ms), dtype=bool)
    for cf in calib_folds:
        calib_mask |= validation_mask(ds.t_ms, cf)
    purge_mask = purge_and_embargo_train_mask(ds.t_ms, ds.horizon_ms, fold, ML.walk_forward.embargo_hours) & ~calib_mask
    # the purge/embargo mask (minus calibration rows) must never be a superset of the naive boundary mask
    assert int(purge_mask.sum()) <= int(naive_mask.sum())
    assert np.all(~purge_mask | naive_mask)  # every purge-kept row is also before the boundary
    assert not np.any(purge_mask & calib_mask)  # training and calibration rows are disjoint by construction
    for cf in calib_folds:
        assert cf.valid_end_ms <= fold.valid_start_ms  # every calibration fold is strictly before the window

    hp = ML.hyperparameters.logistic[0].model_dump()
    result = fit_window_model(ds, "logistic", hp, col_idx, folds, idx, ML, APP.project.random_seed)
    if result is not None:
        assert result.n_train == int(purge_mask.sum())
        assert result.n_calib == int(calib_mask.sum())
        assert result.calibration_fold_indices == tuple(cf.fold_index for cf in calib_folds)


def test_fit_window_model_returns_none_for_window_0_no_preceding_fold_to_calibrate_on():
    ds = _real_dataset(seed=4, days=300)
    if len(ds) < 20:
        pytest.skip("seed produced too few rows")
    folds = generate_folds(int(ds.t_ms.min()), int(ds.t_ms.max()) + 1, min_train_months=1, retrain_interval_months=1)
    if not folds:
        pytest.skip("no folds in this synthetic window")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp = ML.hyperparameters.logistic[0].model_dump()
    assert fit_window_model(ds, "logistic", hp, col_idx, folds, 0, ML, APP.project.random_seed) is None


def test_fit_window_model_returns_none_on_a_degenerate_calibration_split():
    """A calibration block (the preceding fold) whose labels are all one class must not silently produce
    a meaningless threshold/calibration."""
    n = 120
    t_ms = np.arange(n, dtype=np.int64) * 3_600_000
    horizon_ms = t_ms + 3_600_000
    x = np.random.default_rng(0).normal(size=(n, 1))
    label = np.concatenate([np.zeros(40, dtype=np.int64), np.zeros(40, dtype=np.int64), (np.arange(40) % 2)])
    from arven.ml.dataset import Dataset

    ds = Dataset(("f1",), t_ms, horizon_ms, np.ones(n, dtype=np.int64), label, np.zeros(n), x, n, 0, 0)
    fold0 = Fold(0, int(t_ms[0]), int(t_ms[40]), int(t_ms[40]), int(t_ms[80]))  # calibration block: all-zero labels
    fold1 = Fold(1, int(t_ms[0]), int(t_ms[80]), int(t_ms[80]), int(t_ms[-1]) + 1)
    hp = ML.hyperparameters.logistic[0].model_dump()
    result = fit_window_model(ds, "logistic", hp, np.array([0]), (fold0, fold1), 1, ML, APP.project.random_seed)
    assert result is None  # fold0 (the calibration block for window 1) is degenerate: all-zero labels


def test_fit_window_model_calibration_lookback_is_capped_by_availability_not_always_exactly_k():
    """Window index 2 has only folds [0, 1] available before it - the lookback must use exactly those two,
    never pad with anything else, even though CALIBRATION_LOOKBACK_FOLDS=4 > 2."""
    from arven.wfo import CALIBRATION_LOOKBACK_FOLDS

    assert CALIBRATION_LOOKBACK_FOLDS == 4
    ds = _real_dataset(seed=5, days=800)
    if len(ds) < 100:
        pytest.skip("seed produced too few rows")
    folds = generate_folds(int(ds.t_ms.min()), int(ds.t_ms.max()) + 1, min_train_months=3, retrain_interval_months=1)
    if len(folds) < 3:
        pytest.skip("too few folds in this synthetic window")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp = ML.hyperparameters.logistic[0].model_dump()
    result = fit_window_model(ds, "logistic", hp, col_idx, folds, 2, ML, APP.project.random_seed)
    if result is not None:
        assert result.calibration_fold_indices == (0, 1)  # capped at what's available, not padded to 4


def test_estimate_matched_reject_rate():
    assert estimate_matched_reject_rate(n_seen=0, n_vetoed=0) is None
    assert estimate_matched_reject_rate(n_seen=100, n_vetoed=98) == pytest.approx(0.98)
    assert estimate_matched_reject_rate(n_seen=10, n_vetoed=0) == 0.0
