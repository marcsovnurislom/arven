"""Stage 7 composition root (mirrors ``arven.runs``/``arven.ml_runs``'s role): all I/O - loading
development/validation data, writing the walk-forward report - lives here; ``arven.wfo`` itself stays free of
direct I/O. Reuses ``arven.runs.load_inputs``/``make_guard`` and ``arven.ml.train``'s existing dataset/
walk-forward/feature-selection functions rather than building parallel ones.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from arven.backtest.engine import Backtester
from arven.backtest.metrics import compute_metrics, summarize_distribution
from arven.core.backtest_config import BacktestConfig
from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.ml_config import MLConfig
from arven.core.regime_config import RegimeConfig
from arven.core.risk_config import RiskConfig
from arven.core.splitguard import BacktestPeriod
from arven.core.strategies_config import StrategiesConfig
from arven.core.time import utc_now
from arven.decision.pipeline import Stage5Pipeline
from arven.ml.filter import MetaFilter, RandomFilter
from arven.ml.splits import generate_folds
from arven.ml.train import build_combined_dataset, select_feature_columns
from arven.runs import load_inputs, make_guard
from arven.wfo import (
    MINIMUM_WINDOWS,
    enforce_minimum_windows,
    estimate_matched_reject_rate,
    fit_window_model,
    is_partial_window,
    resolve_window_for_fold,
    select_hyperparameters_causally,
    shuffle_dataset_labels,
)

MODEL_FAMILIES: tuple[str, ...] = ("logistic", "lightgbm")
KEY_METRICS: tuple[str, ...] = (
    "total_return", "net_pnl_usdt", "sharpe", "sortino", "max_drawdown", "max_intrabar_drawdown",
    "n_trades", "win_rate", "profit_factor", "avg_win_usdt", "avg_loss_usdt", "fees_total",
    "slippage_total", "funding_total", "turnover", "exposure_time", "liquidations",
)


def wfo_dir(app_cfg: AppConfig) -> Path:
    return app_cfg.data.data_dir / "wfo"


def _new_run_id(root: Path, config_hash: str) -> str:
    base = f"wfo-{utc_now():%Y%m%dT%H%M%SZ}-{config_hash[:8]}"
    run_id, k = base, 1
    while (root / run_id).exists():
        k += 1
        run_id = f"{base}-{k}"
    return run_id


def _derived_seed(base_seed: int, *parts: int) -> int:
    """Deterministic, reproducible per-window/per-purpose seed derivation (the same ``SeedSequence``
    technique already used by ``RandomEntry`` and ``RandomFilter`` elsewhere in this repo)."""
    return int(np.random.SeedSequence([base_seed, *parts]).generate_state(1)[0])


def _collect(windows: list[dict[str, Any]], path: tuple[str, ...]) -> list[float]:
    out: list[float] = []
    for w in windows:
        if not w.get("backtested"):
            continue
        node: Any = w
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if node is not None:
            out.append(float(node))
    return out


@dataclass(frozen=True, eq=False)
class WfoOutcome:
    run_id: str
    run_dir: Path | None
    report: dict[str, Any]


def run_stage7(
    app_cfg: AppConfig, ml_cfg: MLConfig, fcfg: FeaturesConfig, regime_cfg: RegimeConfig,
    strategies_cfg: StrategiesConfig, risk_cfg: RiskConfig, bt_cfg: BacktestConfig, out_dir: Path | None = None,
) -> WfoOutcome:
    guard = make_guard(app_cfg)
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    val = guard.resolve(BacktestPeriod.VALIDATION)
    dev_inputs = load_inputs(app_cfg, fcfg, dev)
    val_inputs = load_inputs(app_cfg, fcfg, val)
    dataset = build_combined_dataset(
        dev_inputs.market, dev_inputs.features, val_inputs.market, val_inputs.features,
        regime_cfg, strategies_cfg, risk_cfg, bt_cfg, app_cfg, ml_cfg,
    )

    # BLOCKING: the exact same generate_folds call Stage 6 already uses over this exact range - no
    # separate Stage 7 calendar (spec point: "Do not invent a separate Stage 7 calendar").
    folds = generate_folds(dev.start_ms, val.end_ms, ml_cfg.walk_forward.min_train_months, ml_cfg.walk_forward.retrain_interval_months)
    enforce_minimum_windows(folds)  # raises InsufficientWindowsError below MINIMUM_WINDOWS - never caught here

    step_ms = ml_cfg.walk_forward.retrain_interval_months * 30 * 86_400_000
    seed = app_cfg.project.random_seed

    # Feature-column selection is a pure function of the static Stage 3 registry (required=True flags) -
    # it never reads dataset.label/outcomes at all, so it is trivially causal for every window; computed
    # once per family, reused everywhere below (matches select_feature_columns' own data-independence).
    col_idx_by_family: dict[str, np.ndarray] = {}
    hp_grid_by_family: dict[str, tuple[dict, ...]] = {}
    for family in MODEL_FAMILIES:
        col_idx_by_family[family] = select_feature_columns(dataset, family, fcfg)
        hp_source = ml_cfg.hyperparameters.logistic if family == "logistic" else ml_cfg.hyperparameters.lightgbm
        hp_grid_by_family[family] = tuple(h.model_dump() for h in hp_source)

    windows: list[dict[str, Any]] = []
    for i, fold in enumerate(folds):
        partial = is_partial_window(fold, val.end_ms, step_ms)
        window = resolve_window_for_fold(guard, fold)
        entry: dict[str, Any] = {
            "window_index": i, "valid_start_ms": fold.valid_start_ms, "valid_end_ms": fold.valid_end_ms,
            "partial_window": partial, "backtested": window is not None,
            "skip_reason": None if window is not None else "fold straddles the development/validation config boundary",
            "families": {},
        }
        if window is None:
            windows.append(entry)
            continue

        inputs = load_inputs(app_cfg, fcfg, window)

        baseline_pipeline = Stage5Pipeline(regime_cfg, strategies_cfg, risk_cfg, bt_cfg, ml_filter=None)
        baseline_result = Backtester(app_cfg, bt_cfg, window, inputs.market, inputs.features).run(baseline_pipeline)
        entry["baseline"] = compute_metrics(baseline_result, bt_cfg)

        for family_idx, family in enumerate(MODEL_FAMILIES):
            col_idx = col_idx_by_family[family]
            fam: dict[str, Any] = {}

            if i < 1:
                fam["ml"] = None
                fam["ml_skip_reason"] = "window 0 has no preceding fold to causally calibrate/select a threshold on"
                fam["shuffled"] = None
                fam["random"] = None
                entry["families"][family] = fam
                continue

            # Causal hyperparameter selection: only folds strictly before window i (never fold i itself -
            # see arven.wfo.select_hyperparameters_causally's docstring for the bug this fixes).
            best_hp = select_hyperparameters_causally(dataset, family, hp_grid_by_family[family], col_idx, folds, i, ml_cfg, seed)
            fam["hyperparameters"] = best_hp
            fam["hyperparameter_selection_used_folds"] = [f.fold_index for f in folds[:i]]

            real_fit = fit_window_model(dataset, family, best_hp, col_idx, folds, i, ml_cfg, seed)
            if real_fit is None:
                fam["ml"] = None
                fam["ml_skip_reason"] = "degenerate train/calibration split for this window (fewer than 2 label classes)"
                fam["shuffled"] = None
                fam["random"] = None
            else:
                meta_filter = MetaFilter(real_fit.artifact, model_id=f"wfo-{family}-w{i}")
                ml_result = Backtester(app_cfg, bt_cfg, window, inputs.market, inputs.features).run(
                    Stage5Pipeline(regime_cfg, strategies_cfg, risk_cfg, bt_cfg, ml_filter=meta_filter)
                )
                fam["ml"] = compute_metrics(ml_result, bt_cfg)
                fam["threshold_selection"] = real_fit.threshold_selection
                fam["classification_metrics"] = real_fit.metrics
                fam["calibration_used_folds"] = list(real_fit.calibration_fold_indices)
                fam["n_calib_rows"] = real_fit.n_calib

                shuffled_dataset = shuffle_dataset_labels(dataset, _derived_seed(seed, i, 1, family_idx))
                shuffled_fit = fit_window_model(shuffled_dataset, family, best_hp, col_idx, folds, i, ml_cfg, seed)
                if shuffled_fit is None:
                    fam["shuffled"] = None
                else:
                    shuffled_filter = MetaFilter(shuffled_fit.artifact, model_id=f"wfo-{family}-w{i}-shuffled")
                    shuffled_result = Backtester(app_cfg, bt_cfg, window, inputs.market, inputs.features).run(
                        Stage5Pipeline(regime_cfg, strategies_cfg, risk_cfg, bt_cfg, ml_filter=shuffled_filter)
                    )
                    fam["shuffled"] = compute_metrics(shuffled_result, bt_cfg)

                reject_rate = estimate_matched_reject_rate(meta_filter.n_seen, meta_filter.n_vetoed)
                if reject_rate is None:
                    fam["random"] = None
                else:
                    random_filter = RandomFilter(
                        reject_rate, seed=_derived_seed(seed, i, 2, family_idx), model_id=f"wfo-{family}-w{i}-random"
                    )
                    random_result = Backtester(app_cfg, bt_cfg, window, inputs.market, inputs.features).run(
                        Stage5Pipeline(regime_cfg, strategies_cfg, risk_cfg, bt_cfg, ml_filter=random_filter)
                    )
                    fam["random"] = compute_metrics(random_result, bt_cfg)
                    fam["matched_reject_rate"] = reject_rate

            entry["families"][family] = fam

        windows.append(entry)

    n_backtested = sum(1 for w in windows if w["backtested"])
    distributions: dict[str, Any] = {
        "baseline": {m: summarize_distribution(_collect(windows, ("baseline", m))) for m in KEY_METRICS},
    }
    for family in MODEL_FAMILIES:
        distributions[family] = {
            variant: {m: summarize_distribution(_collect_family(windows, family, variant, m)) for m in KEY_METRICS}
            for variant in ("ml", "shuffled", "random")
        }

    report = {
        "generated_at": utc_now().isoformat(),
        "app_config_hash": app_cfg.config_hash(), "backtest_config_hash": bt_cfg.config_hash(),
        "ml_config_hash": ml_cfg.config_hash(), "regime_config_hash": regime_cfg.config_hash(),
        "strategies_config_hash": strategies_cfg.config_hash(), "risk_config_hash": risk_cfg.config_hash(),
        "development_period": {"start_ms": dev.start_ms, "end_ms": dev.end_ms},
        "validation_period": {"start_ms": val.start_ms, "end_ms": val.end_ms},
        "schedule": {
            "n_windows_generated": len(folds), "minimum_windows": MINIMUM_WINDOWS,
            "n_windows_backtested": n_backtested, "n_windows_boundary_excluded": len(folds) - n_backtested,
            "min_train_months": ml_cfg.walk_forward.min_train_months,
            "retrain_interval_months": ml_cfg.walk_forward.retrain_interval_months,
            "embargo_hours": ml_cfg.walk_forward.embargo_hours,
        },
        "windows": windows,
        "distributions": distributions,
        "touched_test_set": False,
        "random_seed": seed,
    }

    root = out_dir if out_dir is not None else wfo_dir(app_cfg)
    run_id = _new_run_id(root, ml_cfg.config_hash())
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / "report.json.part"
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, run_dir / "report.json")
    return WfoOutcome(run_id, run_dir, report)


def _collect_family(windows: list[dict[str, Any]], family: str, variant: str, metric: str) -> list[float]:
    out: list[float] = []
    for w in windows:
        if not w.get("backtested"):
            continue
        fam = w.get("families", {}).get(family)
        if not fam:
            continue
        node = fam.get(variant)
        if node is None:
            continue
        v = node.get(metric)
        if v is not None:
            out.append(float(v))
    return out
