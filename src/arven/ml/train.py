"""Training orchestration: dataset -> purged/embargoed walk-forward hyperparameter selection -> final
fit -> isotonic calibration -> artifact. Every window this module touches is resolved through
:class:`~arven.core.splitguard.SplitGuard` (``development``/``validation`` only; reusing the exact
mechanism Stage 4/5 already use, not a parallel one) - the sealed test period is never referenced here.

Two phases, both restricted to ``development ∪ validation``:

1. **Hyperparameter selection** (decision D5: a fixed, ≤4-config grid per model family, never searched
   against an outcome-optimised objective beyond that fixed grid): purged/embargoed expanding-window
   walk-forward folds, each config trained on that fold's training rows and scored (raw log-loss) on that
   fold's own held-out validation rows; the config with the best mean fold log-loss is selected per family.
2. **Final artifact**: refit with the selected hyperparameters on the whole ``development`` period, using
   ``validation`` only for early stopping (LightGBM) and for isotonic calibration (decision D6) - this
   matches ``config/splits.yaml``'s own documented role for each period exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from arven.backtest.marketdata import MarketData
from arven.backtest.provider import FeatureData
from arven.core.backtest_config import BacktestConfig
from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.ml_config import MLConfig
from arven.core.regime_config import RegimeConfig
from arven.core.risk_config import RiskConfig
from arven.core.splitguard import AllowedWindow, BacktestPeriod
from arven.core.strategies_config import StrategiesConfig
from arven.features.registry import build_registry
from arven.ml.artifact import ModelArtifact, build_manifest, dataset_fingerprint
from arven.ml.calibration import fit_isotonic
from arven.ml.dataset import Dataset, build_dataset
from arven.ml.metrics import (
    brier_score, calibration_curve, expected_calibration_error, log_loss, precision_coverage_at_thresholds, roc_auc,
)
from arven.ml.model import fit_lightgbm, fit_logistic_regression
from arven.ml.splits import Fold, generate_folds, purge_and_embargo_train_mask, validation_mask

ModelFamily = Literal["logistic", "lightgbm"]

# BLOCKER 2 (Stage 6 pre-commit audit): the minimum number of validation candidates a threshold candidate
# must pass before its precision is trusted for selection - the same statistical-meaningfulness floor
# ``arven.ml_runs.MIN_ELIGIBLE_ROWS`` already uses for "is this dataset big enough to train on at all".
MIN_THRESHOLD_COVERAGE = 20

THRESHOLD_SELECTION_OBJECTIVE = (
    "maximize precision P(label=1 | calibrated_p >= threshold) on VALIDATION-period rows only, restricted to "
    "candidates with at least MIN_THRESHOLD_COVERAGE (20) validation rows passing (so precision is never "
    "estimated from a handful of samples); never optimizes Sharpe, total return or drawdown - precision is a "
    "meta-labeling-appropriate classification objective on the label itself, matching a veto-only filter's job "
    "(reject unless confident), not a trading-return search"
)
THRESHOLD_TIE_BREAK_RULE = (
    "if multiple candidates tie for the best precision, select the LOWEST tied threshold (more permissive: "
    "among equally-precise options, a higher threshold vetoes strictly more candidates for no measured "
    "precision benefit)"
)
THRESHOLD_FALLBACK_RULE = (
    "if no candidate reaches MIN_THRESHOLD_COVERAGE (e.g. a poorly-calibrated model whose scores never reach "
    "the higher candidates), fall back to the smallest configured candidate (the most permissive option) and "
    "record used_fallback=true - never silently report a precision estimated from too few samples"
)


def select_threshold(p_calibrated: np.ndarray, y_calib: np.ndarray, candidates: tuple[float, ...]) -> dict[str, Any]:
    """BLOCKER 2 (Stage 6 pre-commit audit): the approved-but-unimplemented "threshold chosen on validation
    only" behavior. Pure function of its three arguments alone - no window/period/config access of any kind,
    so it is structurally incapable of reaching the sealed test period (locked by
    ``tests/leakage/test_ml_leakage.py``'s signature check) and cannot be influenced by anything outside the
    validation-period arrays the caller passes in (never the final A/B backtest result)."""
    rows = precision_coverage_at_thresholds(y_calib, p_calibrated, candidates)
    eligible = [r for r in rows if r["n_taken"] >= MIN_THRESHOLD_COVERAGE]
    if eligible:
        best_precision = max(r["precision"] for r in eligible)
        tied = [r for r in eligible if r["precision"] == best_precision]
        selected = min(r["threshold"] for r in tied)
        used_fallback = False
    else:
        selected = min(candidates)
        used_fallback = True
    return {
        "candidates": list(candidates),
        "candidate_stats": rows,
        "selected": selected,
        "used_fallback": used_fallback,
        "min_coverage": MIN_THRESHOLD_COVERAGE,
        "objective": THRESHOLD_SELECTION_OBJECTIVE,
        "tie_break_rule": THRESHOLD_TIE_BREAK_RULE,
        "fallback_rule": THRESHOLD_FALLBACK_RULE,
    }


def logistic_required_columns(features_cfg: FeaturesConfig) -> tuple[str, ...]:
    """The Stage 3 columns Stage 3 itself flags ``required=True`` (D7's rule, computed from the real
    registry, never a hand-picked or hardcoded list)."""
    return tuple(s.name for s in build_registry(features_cfg) if s.required and s.name != "feat_ready")


def select_feature_columns(dataset: Dataset, model_family: ModelFamily, features_cfg: FeaturesConfig) -> np.ndarray:
    """Column indices into ``dataset.x`` this model family uses: LightGBM gets everything (all 60 causal
    Stage 3 columns + the 18 Stage 5 context columns); logistic regression gets only the Stage-3-required
    subset + all 18 context columns (context columns are Stage 5-derived and always finite; D7 only
    restricts the Stage 3-sourced portion, which is the part that can be NaN)."""
    if model_family == "lightgbm":
        return np.arange(len(dataset.feature_names))
    required = set(logistic_required_columns(features_cfg))
    from arven.ml.dataset import CONTEXT_COLUMNS

    keep = set(required) | set(CONTEXT_COLUMNS)
    return np.array([i for i, n in enumerate(dataset.feature_names) if n in keep], dtype=np.int64)


def build_combined_dataset(
    dev_market: MarketData, dev_features: FeatureData, val_market: MarketData, val_features: FeatureData,
    regime_cfg: RegimeConfig, strategies_cfg: StrategiesConfig, risk_cfg: RiskConfig, bt_cfg: BacktestConfig,
    app_cfg: AppConfig, ml_cfg: MLConfig,
) -> Dataset:
    """Development and validation replayed and concatenated in time order (the periods are contiguous per
    ``config/splits.yaml``). Never touches ``test``."""
    dev = build_dataset(dev_market, dev_features, regime_cfg, strategies_cfg, risk_cfg, bt_cfg, app_cfg.costs, ml_cfg)
    val = build_dataset(val_market, val_features, regime_cfg, strategies_cfg, risk_cfg, bt_cfg, app_cfg.costs, ml_cfg)
    if len(dev) == 0 and len(val) == 0:
        return dev
    assert dev.feature_names == val.feature_names
    return Dataset(
        dev.feature_names,
        np.concatenate([dev.t_ms, val.t_ms]), np.concatenate([dev.horizon_ms, val.horizon_ms]),
        np.concatenate([dev.action, val.action]), np.concatenate([dev.label, val.label]),
        np.concatenate([dev.net_return, val.net_return]),
        np.concatenate([dev.x, val.x], axis=0) if len(dev) and len(val) else (dev.x if len(dev) else val.x),
        dev.n_candidates_total + val.n_candidates_total,
        dev.n_ineligible_risk + val.n_ineligible_risk, dev.n_ineligible_label + val.n_ineligible_label,
    )


def _standardize(x_train: np.ndarray, x_other: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fit mean/std on ``x_train`` only (architecture rule 7); apply the same transform to both arrays."""
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std = np.where(std > 1e-12, std, 1.0)
    return (x_train - mean) / std, (x_other - mean) / std, mean, std


@dataclass(frozen=True, eq=False)
class FoldResult:
    fold_index: int
    model_family: ModelFamily
    hyperparams: dict
    n_train: int
    n_valid: int
    train_base_rate: float | None
    valid_log_loss: float | None  # RAW, full fold validation block - unchanged, still drives hyperparameter selection
    valid_brier: float | None
    valid_auc: float | None
    # BLOCKER 3 (Stage 6 pre-commit audit, D6): genuine fold-local isotonic calibration, fit on the
    # chronologically-first half of this fold's own validation block and evaluated on the disjoint,
    # chronologically-later second half - never on the training rows, never past the fold's own validation
    # window. `None` when a fold's validation block is too small to split into two non-empty halves (reported
    # honestly via these `None`s, not silently smoothed over or padded with more data).
    n_calib_fit: int | None
    n_calib_eval: int | None
    calib_fit_positive_rate: float | None
    raw_log_loss_calib_eval: float | None  # RAW metric on the SAME held-out half as the calibrated one below (apples-to-apples)
    raw_brier_calib_eval: float | None
    raw_auc_calib_eval: float | None
    calibrated_log_loss: float | None
    calibrated_brier: float | None
    calibrated_ece: float | None


def _fit_one(model_family: ModelFamily, x_train, y_train, x_eval, y_eval, feature_names, hp: dict, ml_cfg: MLConfig, seed: int):
    if model_family == "logistic":
        xt, xe, mean, std = _standardize(x_train, x_eval)
        model = fit_logistic_regression(xt, y_train, feature_names, l2=hp["l2"])
        p_eval = model.predict_proba(xe)
        return model, p_eval, mean, std
    model = fit_lightgbm(
        x_train, y_train, x_eval, y_eval, feature_names, hp, ml_cfg.hyperparameters.n_estimators_max,
        ml_cfg.hyperparameters.early_stopping_rounds, seed,
    )
    return model, model.predict_proba(x_eval), None, None


def run_walk_forward(dataset: Dataset, model_family: ModelFamily, hp_grid: tuple[dict, ...], col_idx: np.ndarray, folds: tuple[Fold, ...], ml_cfg: MLConfig, seed: int) -> tuple[dict, list[FoldResult]]:
    x = dataset.x[:, col_idx]
    results: dict[int, list[FoldResult]] = {i: [] for i in range(len(hp_grid))}
    for fold in folds:
        train_mask = purge_and_embargo_train_mask(dataset.t_ms, dataset.horizon_ms, fold, ml_cfg.walk_forward.embargo_hours)
        valid_mask = validation_mask(dataset.t_ms, fold)
        if not train_mask.any() or not valid_mask.any():
            continue
        x_train, y_train = x[train_mask], dataset.label[train_mask].astype(np.float64)
        x_valid, y_valid = x[valid_mask], dataset.label[valid_mask].astype(np.float64)
        if len(np.unique(y_train)) < 2:
            continue  # a degenerate all-one-class fold cannot train a meaningful classifier
        for i, hp in enumerate(hp_grid):
            model, p_valid, *_ = _fit_one(model_family, x_train, y_train, x_valid, y_valid, dataset.feature_names, hp, ml_cfg, seed)
            ll = log_loss(y_valid, p_valid)

            # BLOCKER 3 (D6): fold-local isotonic calibration - fit on the chronologically-first half of
            # THIS fold's validation block (x_valid/y_valid/p_valid are already in chronological order,
            # inherited from dataset.t_ms), evaluated on the disjoint, later second half. The model itself
            # is unchanged from the raw-metric computation above (same fit, same p_valid) - only the
            # calibration step is fold-local, matching D6's literal "fit per walk-forward fold" wording.
            n_v = len(y_valid)
            half = n_v // 2
            n_calib_fit = n_calib_eval = None
            calib_fit_pos_rate = None
            raw_ll_eval = raw_br_eval = raw_auc_eval = None
            cal_ll = cal_br = cal_ece = None
            if half >= 1 and (n_v - half) >= 1:
                p_fit, y_fit = p_valid[:half], y_valid[:half]
                p_eval, y_eval_ = p_valid[half:], y_valid[half:]
                if len(np.unique(y_fit)) >= 1:  # PAVA tolerates a single class; only an empty fit set is invalid
                    fold_calibrator = fit_isotonic(p_fit, y_fit)
                    p_eval_calibrated = fold_calibrator.predict(p_eval)
                    n_calib_fit, n_calib_eval = int(half), int(n_v - half)
                    calib_fit_pos_rate = float(y_fit.mean())
                    raw_ll_eval, raw_br_eval, raw_auc_eval = log_loss(y_eval_, p_eval), brier_score(y_eval_, p_eval), roc_auc(y_eval_, p_eval)
                    cal_ll = log_loss(y_eval_, p_eval_calibrated)
                    cal_br = brier_score(y_eval_, p_eval_calibrated)
                    cal_ece = expected_calibration_error(y_eval_, p_eval_calibrated)

            results[i].append(FoldResult(
                fold.fold_index, model_family, hp, int(len(y_train)), int(len(y_valid)), float(y_train.mean()),
                ll, brier_score(y_valid, p_valid), roc_auc(y_valid, p_valid),
                n_calib_fit, n_calib_eval, calib_fit_pos_rate,
                raw_ll_eval, raw_br_eval, raw_auc_eval, cal_ll, cal_br, cal_ece,
            ))
    means = {i: (float(np.mean([r.valid_log_loss for r in rs])) if rs else math.inf) for i, rs in results.items()}
    best_i = min(means, key=lambda i: means[i])
    all_results = [r for rs in results.values() for r in rs]
    return hp_grid[best_i], all_results


def train_final_model(
    dataset: Dataset, model_family: ModelFamily, hp: dict, col_idx: np.ndarray, dev_end_ms: int, ml_cfg: MLConfig, seed: int
) -> tuple[ModelArtifact, dict[str, Any]]:
    x = dataset.x[:, col_idx]
    feature_names = tuple(dataset.feature_names[i] for i in col_idx)
    dev_mask = dataset.t_ms < dev_end_ms
    val_mask = ~dev_mask
    x_train, y_train = x[dev_mask], dataset.label[dev_mask].astype(np.float64)
    x_calib, y_calib = x[val_mask], dataset.label[val_mask].astype(np.float64)
    model, p_calib, mean, std = _fit_one(model_family, x_train, y_train, x_calib, y_calib, feature_names, hp, ml_cfg, seed)
    calibrator = fit_isotonic(p_calib, y_calib)
    p_calibrated = calibrator.predict(p_calib)
    # BLOCKER 2: threshold is now genuinely selected on these same validation-only calibrated predictions -
    # never on dev/train rows, never on the sealed test period (unreachable: this module never imports or
    # resolves a sealed period at all, and p_calib/y_calib are already restricted to val_mask by the
    # caller's dev_end_ms).
    threshold_selection = select_threshold(p_calibrated, y_calib, tuple(ml_cfg.threshold.candidates))
    metrics = {
        "raw": {"log_loss": log_loss(y_calib, p_calib), "brier": brier_score(y_calib, p_calib), "roc_auc": roc_auc(y_calib, p_calib)},
        "calibrated": {"log_loss": log_loss(y_calib, p_calibrated), "brier": brier_score(y_calib, p_calibrated), "ece": expected_calibration_error(y_calib, p_calibrated)},
        "calibration_curve": calibration_curve(y_calib, p_calibrated),
        "train_base_rate": float(y_train.mean()) if len(y_train) else None,
        "validation_base_rate": float(y_calib.mean()) if len(y_calib) else None,
    }
    artifact = ModelArtifact(model_family, model, calibrator, feature_names, threshold_selection["selected"], mean, std)
    return artifact, metrics, threshold_selection


def resolve_dev_val_windows(app_cfg: AppConfig, guard) -> tuple[AllowedWindow, AllowedWindow]:
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    val = guard.resolve(BacktestPeriod.VALIDATION)
    return dev, val
