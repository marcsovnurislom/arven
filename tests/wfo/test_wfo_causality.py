"""Regression tests for the causal-evaluation audit (2026-10-01): an evaluation window must never
contribute to any decision (hyperparameters, calibration, threshold) that is then evaluated on it.

These tests would have FAILED against the original implementation, which called
``run_walk_forward(dataset, family, hp_grid, col_idx, folds, ...)`` with **all** folds (window N's own
held-out log-loss included in its own hyperparameter selection), and calibrated/selected a threshold using
``validation_mask(t_ms, fold)`` where ``fold`` was the evaluation window itself.
"""

from unittest.mock import patch

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
from arven.ml.dataset import Dataset, build_dataset
from arven.ml.splits import generate_folds, validation_mask
from arven.ml.train import run_walk_forward, select_feature_columns
from arven.wfo import fit_window_model, select_hyperparameters_causally

REGIME, STRATEGIES, RISK, BT, ML, APP, FEATURES = (
    load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(),
    load_ml_config(), load_config(), load_features_config(),
)


def _dataset_and_folds(seed, days=900, min_train_months=3, retrain_interval_months=1):
    market = random_1m_market(days * 24, seed=seed)
    feats = make_feature_data(days, seed=seed)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    folds = generate_folds(int(ds.t_ms.min()), int(ds.t_ms.max()) + 1, min_train_months, retrain_interval_months)
    return ds, folds


def _perturb_rows(dataset: Dataset, mask: np.ndarray, seed: int) -> Dataset:
    """Replace x/label for exactly the rows selected by `mask` with fresh random garbage - everything
    else byte-identical. The same perturbation technique already used throughout this repo's leakage
    canaries (Stage 3/4/5/6), applied here to one walk-forward window's own rows."""
    rng = np.random.default_rng(seed)
    x = dataset.x.copy()
    label = dataset.label.copy()
    n = int(mask.sum())
    if n:
        x[mask] = rng.normal(0.0, 5.0, size=(n, x.shape[1]))
        label[mask] = rng.integers(0, 2, size=n)
    return Dataset(
        dataset.feature_names, dataset.t_ms, dataset.horizon_ms, dataset.action, label,
        dataset.net_return, x, dataset.n_candidates_total, dataset.n_ineligible_risk, dataset.n_ineligible_label,
    )


# --- 1. direct argument-capture: exactly which folds does run_walk_forward get called with? ----------------


def test_select_hyperparameters_causally_calls_run_walk_forward_with_exactly_the_prior_folds():
    """Deterministic, fast, synthetic: instruments arven.wfo.run_walk_forward directly and asserts the
    `folds` argument it receives is exactly folds[:window_index] - never folds[window_index] itself. This
    is the single most direct possible regression guard against the original bug (which passed `folds`,
    the full tuple, unconditionally)."""
    ds, folds = _dataset_and_folds(seed=1, days=500)
    if len(folds) < 4:
        pytest.skip("too few folds in this synthetic window")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp_grid = tuple(h.model_dump() for h in ML.hyperparameters.logistic)

    for window_index in (1, 2, len(folds) - 1):
        with patch("arven.wfo.run_walk_forward", wraps=run_walk_forward) as spy:
            select_hyperparameters_causally(ds, "logistic", hp_grid, col_idx, folds, window_index, ML, APP.project.random_seed)
        passed_folds = spy.call_args.args[4]  # run_walk_forward(dataset, model_family, hp_grid, col_idx, folds, ...)
        assert passed_folds == folds[:window_index]
        assert folds[window_index] not in passed_folds


def test_select_hyperparameters_causally_falls_back_to_the_first_candidate_for_window_0():
    ds, folds = _dataset_and_folds(seed=2, days=500)
    if not folds:
        pytest.skip("no folds in this synthetic window")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp_grid = tuple(h.model_dump() for h in ML.hyperparameters.logistic)
    best_hp = select_hyperparameters_causally(ds, "logistic", hp_grid, col_idx, folds, 0, ML, APP.project.random_seed)
    assert best_hp == hp_grid[0]  # zero preceding folds -> run_walk_forward's own empty-folds fallback


# --- 2. perturbation invariance: window N's own rows cannot change what gets evaluated on it ---------------


@pytest.mark.parametrize("seed", [10, 11])
def test_hyperparameter_selection_for_window_n_is_invariant_to_perturbing_window_n_itself(seed):
    ds, folds = _dataset_and_folds(seed=seed, days=900)
    idx = next((i for i in range(2, len(folds)) if int((ds.t_ms < folds[i].valid_start_ms).sum()) > 60), None)
    if idx is None:
        pytest.skip("no usable window in this synthetic dataset")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp_grid = tuple(h.model_dump() for h in ML.hyperparameters.logistic)

    base_hp = select_hyperparameters_causally(ds, "logistic", hp_grid, col_idx, folds, idx, ML, APP.project.random_seed)

    window_mask = validation_mask(ds.t_ms, folds[idx])
    perturbed = _perturb_rows(ds, window_mask, seed=seed + 1000)
    perturbed_hp = select_hyperparameters_causally(perturbed, "logistic", hp_grid, col_idx, folds, idx, ML, APP.project.random_seed)

    assert base_hp == perturbed_hp


@pytest.mark.parametrize("seed", [20, 21])
def test_fit_window_model_result_for_window_n_is_invariant_to_perturbing_window_n_itself(seed):
    """The complementary check for the SECOND violation the audit found: calibration + threshold must not
    change when the evaluation window's own rows are perturbed - only the preceding fold (the real
    calibration source) may affect them."""
    ds, folds = _dataset_and_folds(seed=seed, days=900)
    idx = next((i for i in range(2, len(folds)) if int((ds.t_ms < folds[i].valid_start_ms).sum()) > 60), None)
    if idx is None:
        pytest.skip("no usable window in this synthetic dataset")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp = ML.hyperparameters.logistic[0].model_dump()

    base = fit_window_model(ds, "logistic", hp, col_idx, folds, idx, ML, APP.project.random_seed)
    if base is None:
        pytest.skip("degenerate split for this seed/window")

    window_mask = validation_mask(ds.t_ms, folds[idx])
    perturbed_ds = _perturb_rows(ds, window_mask, seed=seed + 2000)
    perturbed = fit_window_model(perturbed_ds, "logistic", hp, col_idx, folds, idx, ML, APP.project.random_seed)
    assert perturbed is not None

    probe = ds.x[validation_mask(ds.t_ms, folds[idx - 1])][:, col_idx][:5]  # a fixed, UNperturbed probe
    assert np.array_equal(base.artifact.predict_calibrated(probe), perturbed.artifact.predict_calibrated(probe))
    assert base.threshold_selection["selected"] == perturbed.threshold_selection["selected"]
    assert base.n_train == perturbed.n_train and base.n_calib == perturbed.n_calib


@pytest.mark.parametrize("seed", [30])
def test_fit_window_model_result_for_window_n_DOES_change_if_the_calibration_block_changes(seed):
    """Sanity check that the invariance tests above are actually meaningful (not trivially insensitive to
    every perturbation): perturbing the PRECEDING fold (the real, legitimate calibration source) must
    change the calibration/threshold - proving the function is genuinely data-dependent, just causally so."""
    ds, folds = _dataset_and_folds(seed=seed, days=900)
    idx = next((i for i in range(2, len(folds)) if int((ds.t_ms < folds[i].valid_start_ms).sum()) > 60), None)
    if idx is None:
        pytest.skip("no usable window in this synthetic dataset")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp = ML.hyperparameters.logistic[0].model_dump()

    base = fit_window_model(ds, "logistic", hp, col_idx, folds, idx, ML, APP.project.random_seed)
    if base is None:
        pytest.skip("degenerate split for this seed/window")

    calib_mask = validation_mask(ds.t_ms, folds[idx - 1])
    perturbed_ds = _perturb_rows(ds, calib_mask, seed=seed + 3000)
    perturbed = fit_window_model(perturbed_ds, "logistic", hp, col_idx, folds, idx, ML, APP.project.random_seed)
    if perturbed is None:
        pytest.skip("perturbation degenerated the calibration split for this seed")

    probe = ds.x[calib_mask][:, col_idx][:5]
    changed = not np.array_equal(base.artifact.predict_calibrated(probe), perturbed.artifact.predict_calibrated(probe))
    assert changed or base.threshold_selection["selected"] != perturbed.threshold_selection["selected"]
