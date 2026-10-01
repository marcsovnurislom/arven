"""Stage 7: walk-forward robustness evaluation over ``development ∪ validation`` (2020-01-01 -> 2025-01-01)
only. Never resolves the sealed test period - it remains locked for Stage 10
(``tests/leakage/test_wfo_leakage.py`` statically enforces this).

Reuses Stage 6's existing primitives unchanged: ``arven.ml.splits.generate_folds`` (the exact same
17-window schedule Stage 6 already produces over this exact range, with the already-approved
``min_train_months=12``/``retrain_interval_months=3`` from ``config/ml.yaml``),
``purge_and_embargo_train_mask``/``validation_mask`` (the same purge/embargo discipline), ``_fit_one``/
``fit_isotonic`` (the same model-fitting and calibration primitives), and ``select_threshold`` (the same
validation-only threshold selection). The one genuinely new composition (:func:`fit_window_model`) exists
because neither existing Stage 6 entry point does what Stage 7 needs: ``run_walk_forward`` purges/embargoes
correctly but only returns classification metrics (discards the fitted model); ``train_final_model`` returns
a full deployable artifact but splits train/calibration with a naive ``t_ms < boundary`` cut that is only
safe at Stage 6's single, data-bounded dev/val edge (see module docstring below on why) - not at Stage 7's
17 *interior* window boundaries, where it would leak.

**Why ``train_final_model``'s boundary split cannot be reused directly for interior windows:** Stage 6's
combined dataset is built from market data spanning the *entire* development+validation range, not
re-bounded per window. A row's triple-barrier label can only fail to resolve (and so be excluded) if its
horizon runs past the *stored market data's own end* - which only happens at the dataset's true edges (the
dev/val config boundary, where Stage 6's original design happened to be safe "for free" - documented as an
emergent property, not an explicit purge, in ``docs/current_state.md`` open issue #8). At any of Stage 7's
interior fold boundaries, no such boundedness exists: a training row just before ``fold.valid_start_ms`` can
have a label horizon that resolves using data *inside* the window it would be evaluated against. Purging and
embargo (exactly Stage 6's own ``purge_and_embargo_train_mask``) are the existing, already-audited mechanism
for exactly this problem - so :func:`fit_window_model` uses it, rather than inventing a new one.

**Corrected causal design (2026-10-01), superseding an earlier, invalid version of this module:** the
original implementation selected hyperparameters *once globally*, via ``run_walk_forward(dataset, family,
hp_grid, col_idx, folds, ...)`` called with **all 17 folds** - meaning window N's own held-out log-loss
contributed to the hyperparameter choice that was then *evaluated on window N*. A second, independent
violation existed in ``fit_window_model``: its calibration+threshold step used ``validation_mask(t_ms,
fold)`` where ``fold`` was window N itself - so the MetaFilter's calibration curve and decision threshold
for window N were fit on window N's own labels, then backtested on window N. Both are fixed:

- :func:`select_hyperparameters_causally` selects hyperparameters for window N using only
  ``folds[:N]`` (every fold *strictly before* N, via the same unmodified ``run_walk_forward``) - window N's
  own fold is never in that list. With zero preceding folds (N=0), ``run_walk_forward`` already falls back
  to ``hp_grid[0]`` for an empty fold list (its own existing behavior, not a new special case here).
- :func:`fit_window_model` now requires ``window_index >= 1``: training uses
  ``purge_and_embargo_train_mask`` relative to window N *minus* the calibration block's own rows;
  calibration + threshold selection use ``validation_mask`` on the last :data:`CALIBRATION_LOOKBACK_FOLDS`
  folds strictly before N - never window N itself. Window 0 has no preceding fold and is therefore never
  evaluated (``fit_window_model`` returns ``None`` for it, exactly like any other degenerate case).

Both changes reuse ``run_walk_forward``/``purge_and_embargo_train_mask``/``validation_mask`` completely
unchanged - the fix is entirely about *which fold indices are passed to them*, not new leakage-prevention
logic. See ``tests/wfo/test_wfo_causality.py`` for the perturbation-invariance regression tests this
directly enables (window N's own data provably cannot change what gets evaluated on it).

**Calibration-block-size revision (2026-10-01, separate from the causal-correction above):** the post-fix
diagnostic audit found a single preceding fold was too small for stable isotonic calibration (PAVA collapses
most scores toward the block's own base rate on ~150-250 rows, so almost nothing crosses even the most
permissive threshold candidate). :data:`CALIBRATION_LOOKBACK_FOLDS` (4) widens the calibration block to the
last 4 folds before window N - a purely statistical fix, still strictly prior to N, still isotonic (D6),
still the same fixed threshold candidate list. See :func:`fit_window_model`'s docstring for the full
rationale.

**Exactly one of the 17 folds (index 10 in the real schedule) straddles the development/validation config
boundary** (2023-07-01) and is therefore *not* backtestable through ``SplitGuard`` as-is (a single
``AllowedWindow`` cannot cross a period boundary, by design - see ``core/splitguard.py``, unmodified here).
Splitting that one window into two separately-resolved, separately-initialized sub-backtests was considered
and rejected: it would require inventing an equity-chaining rule the specification never asked for, for a
single edge-case window. Instead that one fold is excluded from backtesting (kept in the schedule and its
classification-only masks/hp-selection role, since those don't need ``SplitGuard``) - 16 of 17 windows get a
baseline (Stage 5 only) backtest.

**Window 0 additionally has no ML result** (baseline still runs - it needs no training at all): with no
preceding fold, there is nothing to causally calibrate or select a threshold from, so
:func:`fit_window_model` returns ``None`` for it by construction. With ``CALIBRATION_LOOKBACK_FOLDS=4``,
early windows with too little remaining training data after the (now larger) calibration reservation may
also degenerate to ``None`` - reported honestly per window (``ml_skip_reason``) rather than hidden; the
real count is confirmed in ``docs/current_state.md``'s Stage 7 section, not hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from arven.core.ml_config import MLConfig
from arven.core.splitguard import AllowedWindow, BacktestPeriod, SplitGuard
from arven.ml.artifact import ModelArtifact
from arven.ml.calibration import fit_isotonic
from arven.ml.dataset import Dataset
from arven.ml.metrics import brier_score, expected_calibration_error, log_loss, roc_auc
from arven.ml.splits import Fold, purge_and_embargo_train_mask, validation_mask
from arven.ml.train import ModelFamily, _fit_one, run_walk_forward, select_threshold

MINIMUM_WINDOWS = 12  # Stage 7 spec: refuse aggregate/distribution reporting below this many windows


class InsufficientWindowsError(Exception):
    """Fewer than :data:`MINIMUM_WINDOWS` walk-forward windows were generated - reported honestly, never
    silently worked around (mirrors ``arven.ml_runs.InsufficientDataError``'s existing pattern)."""

    def __init__(self, n_windows: int) -> None:
        super().__init__(f"only {n_windows} walk-forward windows generated (minimum required: {MINIMUM_WINDOWS})")
        self.n_windows = n_windows


def enforce_minimum_windows(folds: tuple[Fold, ...]) -> None:
    if len(folds) < MINIMUM_WINDOWS:
        raise InsufficientWindowsError(len(folds))


def is_partial_window(fold: Fold, schedule_end_ms: int, step_ms: int) -> bool:
    """A window is partial if it is shorter than the configured step (only ever the last window, per
    ``generate_folds``'s own clipping to ``window_end_ms``)."""
    return (fold.valid_end_ms - fold.valid_start_ms) < step_ms


def resolve_window_for_fold(guard: SplitGuard, fold: Fold) -> AllowedWindow | None:
    """The ``AllowedWindow`` for one walk-forward window's *evaluation* block
    (``fold.valid_start_ms`` -> ``fold.valid_end_ms``), resolved through the real, unmodified
    :class:`SplitGuard` - never a hand-built window. Returns ``None`` if the fold straddles the
    development/validation config boundary (see module docstring)."""
    dev_start, dev_end = guard.period_bounds(BacktestPeriod.DEVELOPMENT)
    val_start, val_end = guard.period_bounds(BacktestPeriod.VALIDATION)
    if dev_start <= fold.valid_start_ms and fold.valid_end_ms <= dev_end:
        return guard.resolve(BacktestPeriod.DEVELOPMENT, fold.valid_start_ms, fold.valid_end_ms)
    if val_start <= fold.valid_start_ms and fold.valid_end_ms <= val_end:
        return guard.resolve(BacktestPeriod.VALIDATION, fold.valid_start_ms, fold.valid_end_ms)
    return None


def shuffle_dataset_labels(dataset: Dataset, seed: int) -> Dataset:
    """The shuffled-label control (D20, already approved and used by Stage 6's own
    ``shuffle_labels_seed``): permute ``label`` only, independent of ``t_ms``, so any real
    feature/regime/strategy-vs-outcome relationship is destroyed while purging, embargo, calibration and
    threshold selection all run identically to a real window. Mirrors ``arven.ml_runs.train_and_save``'s
    existing inline shuffle exactly, not a new technique."""
    rng = np.random.default_rng(seed)
    shuffled_label = dataset.label[rng.permutation(len(dataset))]
    return Dataset(
        dataset.feature_names, dataset.t_ms, dataset.horizon_ms, dataset.action, shuffled_label,
        dataset.net_return, dataset.x, dataset.n_candidates_total, dataset.n_ineligible_risk, dataset.n_ineligible_label,
    )


CALIBRATION_LOOKBACK_FOLDS = 4  # 2026-10-01 design revision, see fit_window_model's docstring for why


@dataclass(frozen=True, eq=False)
class WindowModelResult:
    artifact: ModelArtifact
    metrics: dict[str, Any]
    threshold_selection: dict[str, Any]
    n_train: int
    n_calib: int
    calibration_fold_indices: tuple[int, ...]


def select_hyperparameters_causally(
    dataset: Dataset, model_family: ModelFamily, hp_grid: tuple[dict, ...], col_idx: np.ndarray,
    folds: tuple[Fold, ...], window_index: int, ml_cfg: MLConfig, seed: int,
) -> dict:
    """Hyperparameters for evaluation window ``window_index``, selected using only ``folds[:window_index]``
    (every fold strictly before it) - window ``window_index`` itself is never in that list, so its own
    held-out log-loss can never influence the hyperparameters later evaluated on it. Reuses
    ``run_walk_forward`` completely unchanged; with zero preceding folds (``window_index == 0``) it already
    falls back to ``hp_grid[0]`` for an empty fold tuple - no special-casing needed here."""
    prior_folds = folds[:window_index]
    best_hp, _fold_results = run_walk_forward(dataset, model_family, hp_grid, col_idx, prior_folds, ml_cfg, seed)
    return best_hp


def fit_window_model(
    dataset: Dataset, model_family: ModelFamily, hp: dict, col_idx: np.ndarray, folds: tuple[Fold, ...],
    window_index: int, ml_cfg: MLConfig, seed: int,
) -> WindowModelResult | None:
    """Fit + calibrate + select-threshold for evaluation window ``window_index``, using externally-supplied
    hyperparameters ``hp`` (from :func:`select_hyperparameters_causally`, already restricted to prior
    folds). Requires ``window_index >= 1``: calibration + threshold selection use the union of
    ``validation_mask(t_ms, f)`` for the last :data:`CALIBRATION_LOOKBACK_FOLDS` folds strictly before
    ``window_index`` (never ``folds[window_index]``, the window being evaluated). Training rows: everything
    ``purge_and_embargo_train_mask`` (relative to ``folds[window_index]``, Stage 6's own function,
    unmodified) would allow, *minus* whichever rows are reserved for calibration, so no row is ever used
    for both. Returns ``None`` (not a degenerate fit) if window_index is 0, or if either split has fewer
    than 2 label classes - reported honestly by the caller, never silently skipped.

    **Why a lookback of several folds, not just one (2026-10-01 design revision):** the Stage 7 diagnostic
    audit found a single preceding fold (~150-250 rows) is too small for isotonic calibration - PAVA
    collapses most calibrated scores toward the calibration block's own base rate, so almost nothing crosses
    even the most permissive threshold candidate (0.50), independent of whether the underlying raw score
    would have ranked candidates sensibly. Widening the calibration block to the last
    ``CALIBRATION_LOOKBACK_FOLDS`` folds is a purely statistical fix (more rows to calibrate on) - it does
    not touch the calibration method (still isotonic, D6), the threshold candidate list, or the causal
    hyperparameter-selection logic, and every added row is still strictly prior to ``window_index`` by
    construction (each of those folds' own ``valid_end_ms`` is at or before ``folds[window_index].valid_start_ms``,
    since folds are chronological)."""
    if window_index < 1:
        return None
    fold = folds[window_index]
    calib_folds = folds[max(0, window_index - CALIBRATION_LOOKBACK_FOLDS):window_index]
    x = dataset.x[:, col_idx]
    feature_names = tuple(dataset.feature_names[i] for i in col_idx)
    calib_mask = np.zeros(len(dataset.t_ms), dtype=bool)
    for cf in calib_folds:
        calib_mask |= validation_mask(dataset.t_ms, cf)
    train_mask = purge_and_embargo_train_mask(dataset.t_ms, dataset.horizon_ms, fold, ml_cfg.walk_forward.embargo_hours) & ~calib_mask
    x_train, y_train = x[train_mask], dataset.label[train_mask].astype(np.float64)
    x_calib, y_calib = x[calib_mask], dataset.label[calib_mask].astype(np.float64)
    if len(np.unique(y_train)) < 2 or len(np.unique(y_calib)) < 2 or len(y_train) == 0 or len(y_calib) == 0:
        return None

    model, p_calib, mean, std = _fit_one(model_family, x_train, y_train, x_calib, y_calib, feature_names, hp, ml_cfg, seed)
    calibrator = fit_isotonic(p_calib, y_calib)
    p_calibrated = calibrator.predict(p_calib)
    threshold_selection = select_threshold(p_calibrated, y_calib, tuple(ml_cfg.threshold.candidates))
    metrics = {
        "raw": {"log_loss": log_loss(y_calib, p_calib), "brier": brier_score(y_calib, p_calib), "roc_auc": roc_auc(y_calib, p_calib)},
        "calibrated": {
            "log_loss": log_loss(y_calib, p_calibrated), "brier": brier_score(y_calib, p_calibrated),
            "ece": expected_calibration_error(y_calib, p_calibrated),
        },
        "train_base_rate": float(y_train.mean()), "calib_base_rate": float(y_calib.mean()),
    }
    artifact = ModelArtifact(model_family, model, calibrator, feature_names, threshold_selection["selected"], mean, std)
    return WindowModelResult(
        artifact, metrics, threshold_selection, int(len(y_train)), int(len(y_calib)),
        tuple(cf.fold_index for cf in calib_folds),
    )


def estimate_matched_reject_rate(n_seen: int, n_vetoed: int) -> float | None:
    """The empirical reject rate a real MetaFilter achieved on this window's own candidates (read from its
    ``n_seen``/``n_vetoed`` counters after running its backtest) - the rate a ``RandomFilter`` control for
    the same window is matched to. ``None`` if the real filter saw no candidates at all (nothing to match)."""
    if n_seen == 0:
        return None
    return n_vetoed / n_seen


VariantName = Literal["baseline", "ml", "shuffled", "random"]
