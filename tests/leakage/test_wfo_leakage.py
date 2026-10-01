"""Stage 7 leakage protection: the walk-forward evaluation must never resolve ``BacktestPeriod.TEST`` /
the sealed test period, anywhere - mirrors the exact static-scan pattern already used for Stage 6
(``tests/leakage/test_ml_leakage.py::test_ml_runs_module_never_resolves_the_test_period`` and
``test_threshold_selection_is_never_called_with_the_test_period``).
"""

from pathlib import Path

import numpy as np
import pytest

from arven.core.config import load_config
from arven.core.splitguard import BacktestPeriod, SealedAccessError, SplitGuard
from arven.ml.splits import Fold, generate_folds
from arven.wfo import resolve_window_for_fold

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
APP = load_config()


def test_wfo_source_files_never_contain_the_literal_BacktestPeriod_TEST():
    for name in ("wfo.py", "wfo_runs.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        assert "BacktestPeriod.TEST" not in text, name
        assert "allow_sealed" not in text, name  # no path to acknowledge sealed access either


def test_resolve_window_for_fold_never_resolves_the_test_period_even_for_a_fold_deep_inside_it():
    """A fold whose valid_start/valid_end are constructed to fall entirely inside the sealed test period
    must return None (unbacktestable), never silently resolve BacktestPeriod.TEST."""
    guard = SplitGuard(APP.splits)
    test_start, test_end = guard.period_bounds(BacktestPeriod.TEST)
    fold = Fold(0, test_start, test_start + 3600_000, test_start, test_start + 3600_000)
    assert resolve_window_for_fold(guard, fold) is None


def test_resolve_window_for_fold_raises_sealed_access_error_if_test_were_ever_requested_directly():
    """Belt-and-suspenders: even a direct, deliberate attempt to resolve the test period through the same
    guard Stage 7 uses is refused by SplitGuard itself (unmodified), not by anything wfo.py adds."""
    guard = SplitGuard(APP.splits)
    with pytest.raises(SealedAccessError):
        guard.resolve(BacktestPeriod.TEST)


def test_the_real_wfo_schedule_stays_entirely_inside_development_and_validation():
    """The actual generate_folds(dev.start, val.end, 12, 3) schedule used by Stage 7 - every single
    window's valid_end_ms is at or before validation.end_ms (the sealed test period's start), never beyond."""
    guard = SplitGuard(APP.splits)
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    val = guard.resolve(BacktestPeriod.VALIDATION)
    test_start, _ = guard.period_bounds(BacktestPeriod.TEST)
    folds = generate_folds(dev.start_ms, val.end_ms, 12, 3)
    assert val.end_ms == test_start  # the exact boundary Stage 7 must never cross
    for f in folds:
        assert f.valid_end_ms <= val.end_ms
        assert f.valid_end_ms <= test_start
