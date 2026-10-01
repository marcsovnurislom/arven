"""Stage 7 schedule: the exact existing Stage 6 generate_folds() call, the minimum-windows gate, and
partial-window flagging - no separate Stage 7 calendar.
"""

import pytest

from arven.core.config import load_config
from arven.core.ml_config import load_ml_config
from arven.core.splitguard import BacktestPeriod, SplitGuard
from arven.ml.splits import Fold, generate_folds
from arven.wfo import MINIMUM_WINDOWS, InsufficientWindowsError, enforce_minimum_windows, is_partial_window

APP = load_config()
ML = load_ml_config()


def test_real_schedule_produces_at_least_the_minimum_and_the_expected_17_windows():
    guard = SplitGuard(APP.splits)
    dev, val = guard.resolve(BacktestPeriod.DEVELOPMENT), guard.resolve(BacktestPeriod.VALIDATION)
    folds = generate_folds(dev.start_ms, val.end_ms, ML.walk_forward.min_train_months, ML.walk_forward.retrain_interval_months)
    assert len(folds) == 17  # the exact, already-documented, already-verified real schedule
    assert len(folds) >= MINIMUM_WINDOWS
    enforce_minimum_windows(folds)  # must not raise


def test_enforce_minimum_windows_raises_below_the_floor():
    too_few = tuple(Fold(i, 0, 1, 1, 2) for i in range(MINIMUM_WINDOWS - 1))
    with pytest.raises(InsufficientWindowsError) as exc:
        enforce_minimum_windows(too_few)
    assert exc.value.n_windows == MINIMUM_WINDOWS - 1


def test_enforce_minimum_windows_accepts_exactly_the_floor():
    exactly = tuple(Fold(i, 0, 1, 1, 2) for i in range(MINIMUM_WINDOWS))
    enforce_minimum_windows(exactly)  # must not raise


def test_real_schedule_hyperparameters_are_reused_unchanged_min_train_12_retrain_3():
    assert ML.walk_forward.min_train_months == 12
    assert ML.walk_forward.retrain_interval_months == 3


def test_only_the_final_real_window_is_partial():
    guard = SplitGuard(APP.splits)
    dev, val = guard.resolve(BacktestPeriod.DEVELOPMENT), guard.resolve(BacktestPeriod.VALIDATION)
    folds = generate_folds(dev.start_ms, val.end_ms, ML.walk_forward.min_train_months, ML.walk_forward.retrain_interval_months)
    step_ms = ML.walk_forward.retrain_interval_months * 30 * 86_400_000
    partial_flags = [is_partial_window(f, val.end_ms, step_ms) for f in folds]
    assert partial_flags == [False] * (len(folds) - 1) + [True]
    # the exact, already-documented real partial window: 2024-12-05 -> 2025-01-01
    last = folds[-1]
    assert last.valid_end_ms == val.end_ms
    assert (last.valid_end_ms - last.valid_start_ms) < step_ms


def test_schedule_is_deterministic():
    guard = SplitGuard(APP.splits)
    dev, val = guard.resolve(BacktestPeriod.DEVELOPMENT), guard.resolve(BacktestPeriod.VALIDATION)
    f1 = generate_folds(dev.start_ms, val.end_ms, 12, 3)
    f2 = generate_folds(dev.start_ms, val.end_ms, 12, 3)
    assert f1 == f2
