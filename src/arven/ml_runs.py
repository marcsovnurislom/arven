"""Composition root for Stage 6 (mirrors ``arven.runs``'s role for Stage 4/5): all I/O — loading
development/validation data, writing model artifacts — lives here; ``arven.ml`` itself stays pure. Reuses
``arven.runs.load_inputs`` (the same window-scoped Stage 4 loader) and
``arven.core.splitguard.SplitGuard`` (the same mechanism Stage 4/5 already use) rather than building
parallel ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.ml_config import MLConfig
from arven.core.regime_config import RegimeConfig
from arven.core.risk_config import RiskConfig
from arven.core.splitguard import BacktestPeriod
from arven.core.strategies_config import StrategiesConfig
from arven.core.time import utc_now
from arven.ml.artifact import build_manifest, dataset_fingerprint, save_artifact
from arven.ml.splits import generate_folds
from arven.ml.train import (
    build_combined_dataset,
    logistic_required_columns,
    run_walk_forward,
    select_feature_columns,
    train_final_model,
)
from arven.runs import load_inputs, make_guard


MIN_ELIGIBLE_ROWS = 20  # below this, no fold/calibration split is meaningful; report honestly instead of a degenerate fit


class InsufficientDataError(Exception):
    """Too few eligible candidates (or too little label variety) to train anything meaningful. Carries the
    exact candidate/ineligibility counts so the caller can report them honestly, per the explicit
    instruction not to manufacture data by loosening Stage 5 thresholds."""

    def __init__(self, message: str, n_candidates_total: int, n_ineligible_risk: int, n_ineligible_label: int, n_eligible: int) -> None:
        super().__init__(message)
        self.n_candidates_total = n_candidates_total
        self.n_ineligible_risk = n_ineligible_risk
        self.n_ineligible_label = n_ineligible_label
        self.n_eligible = n_eligible


def models_dir(app_cfg: AppConfig) -> Path:
    return app_cfg.data.data_dir / "models"


def _new_model_id(root: Path, config_hash: str, model_family: str) -> str:
    base = f"{model_family}-{utc_now():%Y%m%dT%H%M%SZ}-{config_hash[:8]}"
    model_id, k = base, 1
    while (root / model_id).exists():
        k += 1
        model_id = f"{base}-{k}"
    return model_id


@dataclass(frozen=True, eq=False)
class TrainOutcome:
    model_id: str
    model_dir: Path
    manifest: dict[str, Any]
    fold_results: list


def train_and_save(
    app_cfg: AppConfig, ml_cfg: MLConfig, features_cfg: FeaturesConfig, regime_cfg: RegimeConfig,
    strategies_cfg: StrategiesConfig, risk_cfg: RiskConfig, bt_cfg, model_family: str, out_dir: Path | None = None,
    shuffle_labels_seed: int | None = None,
) -> TrainOutcome:
    """``shuffle_labels_seed``: the shuffled-label control (decision D20/point 20) - labels are permuted
    with a fixed seed, independent of ``t_ms``, before hyperparameter selection and the final fit, so any
    real feature/regime/strategy-vs-outcome relationship is destroyed while every other step (purging,
    embargo, calibration, artifact provenance) runs identically to a real training run."""
    guard = make_guard(app_cfg)
    dev_window = guard.resolve(BacktestPeriod.DEVELOPMENT)
    val_window = guard.resolve(BacktestPeriod.VALIDATION)

    dev_inputs = load_inputs(app_cfg, features_cfg, dev_window)
    val_inputs = load_inputs(app_cfg, features_cfg, val_window)
    dataset = build_combined_dataset(
        dev_inputs.market, dev_inputs.features, val_inputs.market, val_inputs.features,
        regime_cfg, strategies_cfg, risk_cfg, bt_cfg, app_cfg, ml_cfg,
    )

    if shuffle_labels_seed is not None:
        import numpy as np

        rng = np.random.default_rng(shuffle_labels_seed)
        shuffled_label = dataset.label[rng.permutation(len(dataset))]
        dataset = type(dataset)(
            dataset.feature_names, dataset.t_ms, dataset.horizon_ms, dataset.action, shuffled_label,
            dataset.net_return, dataset.x, dataset.n_candidates_total, dataset.n_ineligible_risk, dataset.n_ineligible_label,
        )

    n_eligible = len(dataset)
    if n_eligible < MIN_ELIGIBLE_ROWS or len(np_unique_labels(dataset)) < 2:
        raise InsufficientDataError(
            f"only {n_eligible} eligible candidates (of {dataset.n_candidates_total} total; "
            f"{dataset.n_ineligible_risk} rejected by risk rules, {dataset.n_ineligible_label} unresolvable labels) "
            f"in development+validation - below the minimum ({MIN_ELIGIBLE_ROWS}) for a meaningful train/calibration "
            "split. Not manufacturing more samples by loosening Stage 5 thresholds.",
            dataset.n_candidates_total, dataset.n_ineligible_risk, dataset.n_ineligible_label, n_eligible,
        )

    warnings: list[str] = []
    if n_eligible < 100:
        warnings.append(f"only {n_eligible} eligible candidates in development+validation: results are not statistically meaningful")

    col_idx = select_feature_columns(dataset, model_family, features_cfg)  # type: ignore[arg-type]
    hp_grid = tuple(h.model_dump() for h in (ml_cfg.hyperparameters.logistic if model_family == "logistic" else ml_cfg.hyperparameters.lightgbm))
    folds = generate_folds(dev_window.start_ms, val_window.end_ms, ml_cfg.walk_forward.min_train_months, ml_cfg.walk_forward.retrain_interval_months)
    if not folds:
        warnings.append("no walk-forward folds fit inside development+validation with the configured min_train_months")

    seed = app_cfg.project.random_seed
    best_hp, fold_results = ({}, [])
    if folds and len(dataset) >= 2 and len(np_unique_labels(dataset)) == 2:
        best_hp, fold_results = run_walk_forward(dataset, model_family, hp_grid, col_idx, folds, ml_cfg, seed)  # type: ignore[arg-type]
    else:
        best_hp = hp_grid[0] if hp_grid else {}
        warnings.append("insufficient data/label variety for walk-forward hyperparameter selection: used the grid's first configuration")

    artifact, final_metrics, threshold_selection = train_final_model(dataset, model_family, best_hp, col_idx, dev_window.end_ms, ml_cfg, seed)  # type: ignore[arg-type]

    x_sel = dataset.x[:, col_idx]
    fingerprint = dataset_fingerprint(dataset.t_ms, x_sel, dataset.label)
    fold_summary = [
        {
            "fold_index": r.fold_index, "hyperparams": r.hyperparams, "n_train": r.n_train, "n_valid": r.n_valid,
            "train_base_rate": r.train_base_rate, "valid_log_loss": r.valid_log_loss, "valid_brier": r.valid_brier, "valid_auc": r.valid_auc,
            # BLOCKER 3 (D6): fold-local isotonic calibration, fit/evaluated on disjoint halves of this fold's
            # own validation block - None fields mean the fold's validation block was too small to split.
            "n_calib_fit": r.n_calib_fit, "n_calib_eval": r.n_calib_eval, "calib_fit_positive_rate": r.calib_fit_positive_rate,
            "raw_log_loss_calib_eval": r.raw_log_loss_calib_eval, "raw_brier_calib_eval": r.raw_brier_calib_eval,
            "raw_auc_calib_eval": r.raw_auc_calib_eval, "calibrated_log_loss": r.calibrated_log_loss,
            "calibrated_brier": r.calibrated_brier, "calibrated_ece": r.calibrated_ece,
        }
        for r in fold_results
    ]

    root = out_dir if out_dir is not None else models_dir(app_cfg)
    family_tag = f"{model_family}-shuffled" if shuffle_labels_seed is not None else model_family
    model_id = _new_model_id(root, ml_cfg.config_hash(), family_tag)
    manifest = build_manifest(
        model_id=model_id, artifact=artifact, feature_version=features_cfg.version,
        feature_definition_hash=_feature_definition_hash(features_cfg), feature_content_hash=_feature_content_hash(app_cfg, features_cfg),
        ml_config_hash=ml_cfg.config_hash(), app_config_hash=app_cfg.config_hash(), backtest_config_hash=bt_cfg.config_hash(),
        regime_config_hash=regime_cfg.config_hash(), strategies_config_hash=strategies_cfg.config_hash(), risk_config_hash=risk_cfg.config_hash(),
        training_period=(dev_window.start_ms, dev_window.end_ms), validation_period=(val_window.start_ms, val_window.end_ms),
        random_seed=seed, hyperparameters=best_hp, fold_summary=fold_summary, train_dataset_fingerprint=fingerprint,
        metrics=final_metrics, n_candidates_total=dataset.n_candidates_total, n_ineligible_risk=dataset.n_ineligible_risk,
        n_ineligible_label=dataset.n_ineligible_label, n_train_rows=int((dataset.t_ms < dev_window.end_ms).sum()),
        n_calibration_rows=int((dataset.t_ms >= dev_window.end_ms).sum()), warnings=warnings,
        threshold_selection=threshold_selection,
    )
    manifest["shuffled_label_control"] = shuffle_labels_seed is not None
    model_dir = root / model_id
    save_artifact(model_dir, artifact, manifest)
    return TrainOutcome(model_id, model_dir, manifest, fold_results)


def np_unique_labels(dataset):
    import numpy as np

    return np.unique(dataset.label) if len(dataset) else np.array([])


def _feature_definition_hash(features_cfg: FeaturesConfig) -> str:
    from arven.features.registry import definition_hash

    return definition_hash(features_cfg)


def _feature_content_hash(app_cfg: AppConfig, features_cfg: FeaturesConfig) -> str:
    from arven.data.storage import feature_store

    directory = feature_store.cache_dir(app_cfg.data.data_dir, features_cfg.version)
    manifest = feature_store.read_manifest(directory)
    return manifest["data_sha256"]


def load_meta_filter(app_cfg: AppConfig, model_id: str):
    from arven.ml.artifact import load_artifact
    from arven.ml.filter import MetaFilter

    directory = models_dir(app_cfg) / model_id
    artifact, _manifest = load_artifact(directory)
    return MetaFilter(artifact, model_id)
