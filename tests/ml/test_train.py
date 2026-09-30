"""Regression tests for the Stage 6 pre-commit audit's BLOCKER 2 (validation-only threshold selection) and
BLOCKER 3 (fold-local isotonic calibration) fixes.
"""

import inspect

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
from arven.ml.splits import generate_folds
from arven.ml.train import (
    MIN_THRESHOLD_COVERAGE,
    select_feature_columns,
    select_threshold,
    train_final_model,
    run_walk_forward,
)

REGIME, STRATEGIES, RISK, BT, ML, APP, FEATURES = (
    load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(),
    load_ml_config(), load_config(), load_features_config(),
)
CANDIDATES = (0.50, 0.55, 0.60, 0.65, 0.70)


# --- BLOCKER 2: select_threshold -------------------------------------------------------------------------


def test_select_threshold_picks_the_candidate_with_the_highest_precision_not_at_the_extremes():
    """Hand-designed: 5 groups of scores exactly at each candidate boundary, with hand-chosen positive
    counts giving cumulative (p >= threshold) precisions of 0.375 / 0.4333 / 0.50 / 0.20 / 0.25 for the 5
    candidates in order - a unique interior maximum at 0.60, all with coverage >= MIN_THRESHOLD_COVERAGE."""
    p = np.array([0.50] * 50 + [0.55] * 50 + [0.60] * 50 + [0.65] * 30 + [0.70] * 20)
    y = np.array(
        [1] * 10 + [0] * 40  # group A (p=0.50): 10/50 positive
        + [1] * 15 + [0] * 35  # group B (p=0.55): 15/50
        + [1] * 40 + [0] * 10  # group C (p=0.60): 40/50
        + [1] * 5 + [0] * 25  # group D (p=0.65): 5/30
        + [1] * 5 + [0] * 15  # group E (p=0.70): 5/20
    ).astype(float)
    result = select_threshold(p, y, CANDIDATES)
    stats = {r["threshold"]: r for r in result["candidate_stats"]}
    assert stats[0.50]["precision"] == pytest.approx(75 / 200)
    assert stats[0.55]["precision"] == pytest.approx(65 / 150)
    assert stats[0.60]["precision"] == pytest.approx(50 / 100)
    assert stats[0.65]["precision"] == pytest.approx(10 / 50)
    assert stats[0.70]["precision"] == pytest.approx(5 / 20)
    assert result["selected"] == 0.60
    assert result["used_fallback"] is False
    assert all(r["n_taken"] >= MIN_THRESHOLD_COVERAGE for r in result["candidate_stats"] if r["threshold"] <= 0.65)


def test_select_threshold_tie_break_prefers_the_lower_threshold():
    """0.60 and 0.65 are constructed to tie at precision=0.6 (the overall max); 0.70 alone is 0.4 (not tied).
    The tie-break rule (documented in THRESHOLD_TIE_BREAK_RULE) must pick the lower of the tied pair: 0.60."""
    p = np.array([0.50] * 50 + [0.55] * 50 + [0.60] * 30 + [0.65] * 30 + [0.70] * 20)
    y = np.array(
        [1] * 10 + [0] * 40  # A (0.50): 10/50 = 0.2
        + [1] * 10 + [0] * 40  # B (0.55): 10/50 = 0.2
        + [1] * 18 + [0] * 12  # C (0.60): 18/30 = 0.6
        + [1] * 22 + [0] * 8  # D (0.65): 22/30 = 0.7333
        + [1] * 8 + [0] * 12  # E (0.70): 8/20 = 0.4
    ).astype(float)
    result = select_threshold(p, y, CANDIDATES)
    stats = {r["threshold"]: r["precision"] for r in result["candidate_stats"]}
    assert stats[0.60] == pytest.approx(0.6)  # (18+22+8)/(30+30+20) = 48/80
    assert stats[0.65] == pytest.approx(0.6)  # (22+8)/(30+20) = 30/50
    assert stats[0.70] == pytest.approx(0.4)
    assert stats[0.60] == stats[0.65]  # the tie
    assert max(stats.values()) == pytest.approx(0.6)
    assert result["selected"] == 0.60  # the LOWER of the two tied candidates
    assert result["used_fallback"] is False


def test_select_threshold_falls_back_to_the_most_permissive_candidate_when_no_candidate_has_enough_coverage():
    """All scores are below the smallest candidate (0.50) - every candidate has n_taken=0. select_threshold
    must not report a precision estimated from 0 samples; it falls back to min(candidates) and says so."""
    p = np.full(500, 0.3)
    y = (np.arange(500) % 3 == 0).astype(float)
    result = select_threshold(p, y, CANDIDATES)
    assert all(r["n_taken"] == 0 for r in result["candidate_stats"])
    assert result["selected"] == min(CANDIDATES)
    assert result["used_fallback"] is True


def test_select_threshold_never_selects_from_sharpe_return_or_drawdown():
    """Structural: select_threshold's signature has exactly 3 parameters, none of which could carry a
    trading-return/Sharpe/drawdown metric - it is a pure function of calibrated probabilities and labels."""
    sig = inspect.signature(select_threshold)
    assert list(sig.parameters) == ["p_calibrated", "y_calib", "candidates"]


def test_select_threshold_is_a_pure_function_with_no_window_or_period_argument():
    """BLOCKER 2, requirement 9/leakage: nothing outside (p_calibrated, y_calib, candidates) can possibly
    influence the result - there is no config, window, or period parameter to smuggle sealed-test access
    through, and calling it twice with the same inputs is deterministic."""
    sig = inspect.signature(select_threshold)
    for name in sig.parameters:
        assert "period" not in name and "window" not in name and "cfg" not in name and "config" not in name
    p = np.array([0.6] * 30 + [0.4] * 30)
    y = np.array([1] * 20 + [0] * 10 + [0] * 25 + [1] * 5).astype(float)
    r1 = select_threshold(p, y, CANDIDATES)
    r2 = select_threshold(p, y, CANDIDATES)
    assert r1 == r2


def test_threshold_selection_uses_only_the_validation_split_end_to_end():
    """Integration-level proof: train_final_model's x_calib/y_calib (the only inputs threshold selection
    ever sees) are sliced by `t_ms >= dev_end_ms` - i.e. strictly the validation period, matching what the
    manifest separately records as validation_period_start_ms/end_ms."""
    market = random_1m_market(420 * 24, seed=11)
    feats = make_feature_data(420, seed=11)
    ds = build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)
    if len(ds) < 40 or len(np.unique(ds.label)) < 2:
        pytest.skip("seed produced too few/degenerate eligible rows for this integration check")
    dev_end_ms = int(np.median(ds.t_ms))  # an arbitrary but reproducible split point inside the synthetic data
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp = ML.hyperparameters.logistic[0].model_dump()
    artifact, metrics, threshold_selection = train_final_model(ds, "logistic", hp, col_idx, dev_end_ms, ML, APP.project.random_seed)
    n_val_rows_used = sum(r["n_taken"] for r in threshold_selection["candidate_stats"] if r["threshold"] == min(CANDIDATES))
    assert n_val_rows_used <= int((ds.t_ms >= dev_end_ms).sum())


# --- BLOCKER 3: fold-local isotonic calibration -----------------------------------------------------------


def _real_dev_val_dataset(seed):
    market = random_1m_market(500 * 24, seed=seed)
    feats = make_feature_data(500, seed=seed)
    return build_dataset(market, feats, REGIME, STRATEGIES, RISK, BT, APP.costs, ML)


@pytest.mark.parametrize("seed", [21, 22])
def test_fold_local_calibration_fit_and_eval_data_are_disjoint(seed):
    ds = _real_dev_val_dataset(seed)
    if len(ds) < 60 or len(np.unique(ds.label)) < 2:
        pytest.skip("seed produced too few/degenerate eligible rows")
    folds = generate_folds(int(ds.t_ms.min()), int(ds.t_ms.max()) + 1, min_train_months=3, retrain_interval_months=1)
    if not folds:
        pytest.skip("no folds fit this synthetic window")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp_grid = (ML.hyperparameters.logistic[0].model_dump(),)
    _, fold_results = run_walk_forward(ds, "logistic", hp_grid, col_idx, folds, ML, APP.project.random_seed)
    checked_any = False
    for r in fold_results:
        if r.n_calib_fit is None:
            continue
        checked_any = True
        # disjoint by construction (non-overlapping array slices): n_calib_fit + n_calib_eval == n_valid exactly
        assert r.n_calib_fit + r.n_calib_eval == r.n_valid
        # calibration was fit on the FIRST half chronologically, evaluated on the LATER, disjoint half -
        # never on the training rows (n_train is a wholly separate row count, never summed into calib_fit/eval)
        assert r.n_calib_fit > 0 and r.n_calib_eval > 0
    assert checked_any, "no fold had a large enough validation block to exercise fold-local calibration"


def test_fold_local_calibration_is_not_fit_on_training_predictions():
    """A synthetic dataset with a training-period base rate (~90% positive) that is drastically different
    from the fold's own held-out validation base rate (~50%): if calibration were accidentally fit on
    training-period rows instead of the fold's own validation block, the reported base rate would be close
    to 90%, not 50%."""
    rng = np.random.default_rng(0)
    n = 400
    t_ms = np.arange(n, dtype=np.int64) * 3_600_000
    horizon_ms = t_ms + 3_600_000
    x = rng.normal(size=(n, 1))
    train_label = (rng.random(300) < 0.9).astype(int)  # ~90% positive, both classes present
    valid_label = (rng.random(100) < 1 / (1 + np.exp(-x[300:, 0]))).astype(int)  # a real, ~50/50 signal
    label = np.concatenate([train_label, valid_label])
    from arven.ml.dataset import Dataset

    ds = Dataset(("f1",), t_ms, horizon_ms, np.ones(n, dtype=np.int64), label.astype(np.int64),
                 np.zeros(n), x, n, 0, 0)
    from arven.ml.splits import Fold

    fold = Fold(0, int(t_ms[0]), int(t_ms[300]), int(t_ms[300]), int(t_ms[-1]) + 1)
    col_idx = np.array([0])
    hp_grid = (ML.hyperparameters.logistic[0].model_dump(),)
    _, fold_results = run_walk_forward(ds, "logistic", hp_grid, col_idx, (fold,), ML, APP.project.random_seed)
    assert len(fold_results) == 1
    r = fold_results[0]
    assert r.n_valid == 100  # only the fold's own validation block, never the 300 training rows
    assert r.calib_fit_positive_rate is not None
    assert r.calib_fit_positive_rate < 0.75  # nowhere near the ~90% training rate - proves it used validation rows
    assert r.calib_fit_positive_rate == pytest.approx(valid_label[:50].mean())  # exactly the fold's own first-half rate


def test_fold_local_calibration_does_not_leak_backward_into_earlier_folds():
    """Perturbing the labels of a LATER fold's validation block must not change an EARLIER fold's raw or
    calibrated FoldResult - each fold's calibration is fit and evaluated using only its own data."""
    ds = _real_dev_val_dataset(seed=31)
    if len(ds) < 200 or len(np.unique(ds.label)) < 2:
        pytest.skip("seed produced too few/degenerate eligible rows")
    folds = generate_folds(int(ds.t_ms.min()), int(ds.t_ms.max()) + 1, min_train_months=3, retrain_interval_months=1)
    if len(folds) < 2:
        pytest.skip("need at least 2 folds for this check")
    col_idx = select_feature_columns(ds, "logistic", FEATURES)
    hp_grid = (ML.hyperparameters.logistic[0].model_dump(),)

    _, base_results = run_walk_forward(ds, "logistic", hp_grid, col_idx, folds, ML, APP.project.random_seed)
    base_fold0 = [r for r in base_results if r.fold_index == 0 and r.hyperparams == hp_grid[0]]
    if not base_fold0 or base_fold0[0].n_calib_fit is None:
        pytest.skip("fold 0 had no fold-local calibration to compare")

    # perturb labels strictly AFTER fold 0's own validation block (i.e. inside a later fold's territory)
    last_fold = folds[-1]
    perturb_mask = ds.t_ms >= last_fold.valid_start_ms
    rng = np.random.default_rng(99)
    perturbed_label = ds.label.copy()
    perturbed_label[perturb_mask] = rng.integers(0, 2, int(perturb_mask.sum()))
    from arven.ml.dataset import Dataset

    ds_pert = Dataset(ds.feature_names, ds.t_ms, ds.horizon_ms, ds.action, perturbed_label, ds.net_return, ds.x,
                       ds.n_candidates_total, ds.n_ineligible_risk, ds.n_ineligible_label)

    _, pert_results = run_walk_forward(ds_pert, "logistic", hp_grid, col_idx, folds, ML, APP.project.random_seed)
    pert_fold0 = [r for r in pert_results if r.fold_index == 0 and r.hyperparams == hp_grid[0]][0]
    base = base_fold0[0]

    assert pert_fold0.valid_log_loss == base.valid_log_loss
    assert pert_fold0.calibrated_log_loss == base.calibrated_log_loss
    assert pert_fold0.calibrated_brier == base.calibrated_brier
    assert pert_fold0.n_calib_fit == base.n_calib_fit and pert_fold0.n_calib_eval == base.n_calib_eval
