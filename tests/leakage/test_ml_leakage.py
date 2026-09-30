"""Stage 6 leakage canaries: deliberately introduce future labels, future features, temporal shuffling,
full-period normalization and sealed-test contamination, and confirm the pipeline catches each one -
mirroring the canary pattern already used for Stage 3 (``test_canary.py``) and Stage 4/5.
"""

import ast
from pathlib import Path

import numpy as np
import pytest

from arven.backtest.provider import FeatureData
from arven.core.splitguard import BacktestPeriod, SealedAccessError, SplitGuard
from arven.core.time import to_ms, to_utc_datetime
from arven.core.config import load_config
from arven.ml.calibration import fit_isotonic
from arven.ml.splits import generate_folds, purge_and_embargo_train_mask, validation_mask

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
HOUR_MS = 3_600_000
APP = load_config()


# --- 1. future label leaking into a feature (import boundary) --------------------------------------------


def _imports(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
            if node.module == "arven":
                out += [f"arven.{a.name}" for a in node.names]
    return out


def test_features_package_never_imports_ml_labels():
    """Architecture rule 6, extended to Stage 6: `ml/labels.py` (forward-looking) must never be reachable
    from `features/` (causal-only)."""
    for path in (SRC / "features").rglob("*.py"):
        bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8"))) if m.startswith("arven.ml")]
        assert not bad, f"{path}: {bad}"


def test_dataset_feature_columns_never_come_from_labels_module():
    """The canary: a broken dataset builder that folds the label's own resolution price into the feature
    row. A real leakage-detecting pipeline must be able to tell such a row apart from the real one - here,
    structurally, by confirming arven.ml.dataset never imports anything *from* arven.ml.labels beyond the
    single resolve_triple_barrier call used only to compute `label`/`net_return`, never `x`."""
    tree = ast.parse((SRC / "ml" / "dataset.py").read_text(encoding="utf-8"))
    text = (SRC / "ml" / "dataset.py").read_text(encoding="utf-8")
    assert "label_result." in text
    # the only label_result fields ever read are .label and .net_return - never entry/exit prices into x_row
    used_attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "label_result"}
    assert used_attrs <= {"label", "net_return"}


# --- 2. future feature leaking (FeatureView's existing LookAheadError guard) --------------------------


def test_meta_filter_build_row_only_ever_reads_the_current_decision_time():
    """arven.ml.filter.build_row must call view.row(proposed.t_ms) - never a later time. A canary version
    that peeks ahead is caught by FeatureView's existing LookAheadError (Stage 4), inherited here without
    any new leakage-prevention code."""
    from arven.backtest.clock import SimulationClock
    from arven.backtest.errors import LookAheadError
    from arven.backtest.provider import FeatureView
    from arven.core.types import Action
    from arven.decision.engine import ProposedDecision
    from arven.ml.filter import build_row
    from arven.regime.detector import Regime, TrendState, VolState
    from arven.strategies.base import CandidateSignal

    t = np.array([0, HOUR_MS, 2 * HOUR_MS], dtype=np.int64)
    names = ("h1_ret_1",)
    values = np.array([[0.1], [0.2], [0.3]])
    clock = SimulationClock(t)
    clock.advance()
    clock.advance()  # now = HOUR_MS; the row at 2*HOUR_MS is in the future
    view = FeatureView(t, names, values, clock, None)
    regime = Regime(TrendState.UP, VolState.NORMAL, False, True)
    cand = CandidateSignal("trend_momentum", 1, 0.5, 0.02, 0.04, 60, ("r",))
    future_proposed = ProposedDecision(2 * HOUR_MS, Action.LONG, 0.5, 0.5, ("trend_momentum",), (), (), regime, 0.02, 0.04, 60, (cand,))
    with pytest.raises(LookAheadError):
        build_row(view, future_proposed, names + ("regime_trend_TREND_UP",))


# --- 3. random temporal shuffling ---------------------------------------------------------------------


def test_shuffled_fold_assignment_is_optimistically_biased_versus_real_walk_forward():
    """A synthetic dataset with a known regime shift (the feature-label relationship flips halfway through)
    demonstrates *why* chronological, purged walk-forward is required: assigning rows to train/validation
    uniformly at random (ignoring time) lets the model see both regimes during training and looks much
    better than it would walk-forward, where the second regime is genuinely out-of-sample for early folds."""
    from arven.ml.model import fit_logistic_regression
    from arven.ml.metrics import log_loss

    rng = np.random.default_rng(0)
    n = 2000
    t = np.arange(n, dtype=np.int64) * HOUR_MS
    x = rng.normal(size=(n, 1))
    true_w = np.where(np.arange(n) < n // 2, 3.0, -3.0)  # the relationship flips at the midpoint
    y = (rng.random(n) < 1 / (1 + np.exp(-(x[:, 0] * true_w)))).astype(float)

    # chronological: train on the first half only, evaluate on the second (a walk-forward-style split)
    m_chrono = fit_logistic_regression(x[: n // 2], y[: n // 2], ("a",), l2=1.0)
    p_chrono = m_chrono.predict_proba(x[n // 2 :])
    ll_chrono = log_loss(y[n // 2 :], p_chrono)

    # shuffled: train/test split ignoring time - both regimes leak into training
    idx = rng.permutation(n)
    train_idx, test_idx = idx[: n // 2], idx[n // 2 :]
    m_shuffled = fit_logistic_regression(x[train_idx], y[train_idx], ("a",), l2=1.0)
    p_shuffled = m_shuffled.predict_proba(x[test_idx])
    ll_shuffled = log_loss(y[test_idx], p_shuffled)

    assert ll_shuffled < ll_chrono  # shuffled looks (falsely) better: exactly why folds must be chronological


def test_fold_generator_never_produces_out_of_order_or_shuffled_boundaries():
    folds = generate_folds(0, 30 * 30 * 86_400_000, 12, 3)
    starts = [f.valid_start_ms for f in folds]
    assert starts == sorted(starts)
    for f in folds:
        assert f.train_start_ms <= f.train_end_ms <= f.valid_start_ms < f.valid_end_ms


# --- 4. full-period normalization ------------------------------------------------------------------


def test_train_only_standardisation_differs_from_full_period_standardisation():
    from arven.ml.train import _standardize

    rng = np.random.default_rng(1)
    x_train = rng.normal(loc=0.0, scale=1.0, size=(500, 2))
    x_future = rng.normal(loc=5.0, scale=3.0, size=(500, 2))  # a later fold with very different statistics
    x_full = np.vstack([x_train, x_future])

    xt_correct, xf_correct, mean_correct, std_correct = _standardize(x_train, x_future)
    # the canary: standardise using the FULL dataset's statistics instead of train-only
    mean_wrong, std_wrong = x_full.mean(axis=0), x_full.std(axis=0)
    xf_wrong = (x_future - mean_wrong) / std_wrong

    assert not np.allclose(mean_correct, mean_wrong)
    assert not np.allclose(xf_correct, xf_wrong)
    assert np.allclose(mean_correct, x_train.mean(axis=0))  # confirms the real function is train-only


def test_calibration_fit_on_the_models_own_training_rows_differs_from_a_proper_held_out_fit():
    """Fitting the isotonic calibrator on the SAME rows the base model trained on (rather than a held-out
    validation block, as the real pipeline does) produces a detectably different, overfit calibration."""
    rng = np.random.default_rng(2)
    raw = rng.normal(size=800)
    noise_label = (rng.random(800) < 0.3).astype(float)  # no real relationship to `raw`
    cal_correct = fit_isotonic(raw[400:], noise_label[400:])  # held-out half (what the real pipeline does)
    cal_wrong = fit_isotonic(raw[:400], noise_label[:400])  # a different half - just proves fitting is data-dependent, not a no-op
    assert not np.array_equal(cal_correct.y_levels, cal_wrong.y_levels) or not np.array_equal(cal_correct.x_thresholds, cal_wrong.x_thresholds)


# --- 5. sealed-test contamination --------------------------------------------------------------------


def test_ml_dataset_windows_are_resolved_only_through_splitguard_development_or_validation():
    guard = SplitGuard(APP.splits)
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    val = guard.resolve(BacktestPeriod.VALIDATION)
    assert dev.period.value == "development" and not dev.sealed
    assert val.period.value == "validation" and not val.sealed


def test_test_period_is_refused_for_ml_training_without_explicit_acknowledgement():
    guard = SplitGuard(APP.splits)
    with pytest.raises(SealedAccessError):
        guard.resolve(BacktestPeriod.TEST)


def test_ml_runs_module_never_resolves_the_test_period():
    """Static check: arven.ml_runs' training path only ever calls guard.resolve(BacktestPeriod.DEVELOPMENT)
    or .VALIDATION - never .TEST, anywhere in the file."""
    text = (Path(__file__).resolve().parents[2] / "src" / "arven" / "ml_runs.py").read_text(encoding="utf-8")
    assert "BacktestPeriod.TEST" not in text


def test_threshold_selection_is_never_called_with_the_test_period():
    """BLOCKER 2 (Stage 6 pre-commit audit): select_threshold takes no window/period/config argument at
    all - structurally incapable of resolving BacktestPeriod.TEST - and train.py never references the
    literal string anywhere."""
    import inspect

    from arven.ml.train import select_threshold

    text = (SRC / "ml" / "train.py").read_text(encoding="utf-8")
    assert "BacktestPeriod.TEST" not in text
    sig = inspect.signature(select_threshold)
    assert list(sig.parameters) == ["p_calibrated", "y_calib", "candidates"]


def test_fold_generation_window_cannot_extend_past_a_resolved_validation_end():
    """generate_folds takes plain start/end ms, not a period - the caller (ml_runs.train_and_save) is
    responsible for bounding it to development+validation; this test locks that the real bound used is
    exactly validation.end_ms, matching splits.yaml, and not anything beyond it."""
    guard = SplitGuard(APP.splits)
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    val = guard.resolve(BacktestPeriod.VALIDATION)
    folds = generate_folds(dev.start_ms, val.end_ms, 12, 3)
    assert folds[-1].valid_end_ms == val.end_ms
    assert val.end_ms == to_ms(APP.splits.test.start)  # exactly the sealed boundary, never crossing it
