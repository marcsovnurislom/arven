"""Stage 8 leakage protection: the paper-signal loop must never resolve ``BacktestPeriod.TEST`` or touch the
sealed-test log - mirrors the exact static-scan pattern already used for Stage 6/7
(``tests/leakage/test_ml_leakage.py``, ``tests/leakage/test_wfo_leakage.py``).
"""

from pathlib import Path

import pytest

from arven.core.config import load_config
from arven.core.splitguard import BacktestPeriod, SealedAccessError, SplitGuard, SplitViolation
from arven.core.time import to_ms

SRC = Path(__file__).resolve().parents[2] / "src" / "arven"
APP = load_config()


def test_paper_source_files_never_contain_the_literal_BacktestPeriod_TEST():
    for path in (SRC / "paper").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "BacktestPeriod.TEST" not in text, path
        assert "allow_sealed" not in text, path  # no path to acknowledge sealed access either


def test_forward_resolving_never_falls_back_to_resolving_test():
    """FORWARD and TEST are wholly separate branches in SplitGuard.resolve - resolving a large forward
    window never silently becomes, or is backed by, a TEST-period resolution (never sealed, never logged)."""
    guard = SplitGuard(APP.splits)
    _, test_end = guard.period_bounds(BacktestPeriod.TEST)  # forward_start, in the real config
    w = guard.resolve(BacktestPeriod.FORWARD, end_ms=test_end + 1_000 * 3_600_000)
    assert w.period == BacktestPeriod.FORWARD and not w.sealed and w.sealed_reason is None


def test_forward_refuses_a_start_before_forward_start_even_though_that_equals_the_sealed_tests_end():
    guard = SplitGuard(APP.splits)
    test_start, test_end = guard.period_bounds(BacktestPeriod.TEST)
    with pytest.raises(SplitViolation):
        guard.resolve(BacktestPeriod.FORWARD, start_ms=test_start, end_ms=test_end + 3_600_000)


def test_forward_cannot_be_used_to_reach_backward_into_development_or_validation():
    guard = SplitGuard(APP.splits)
    dev_start, _ = guard.period_bounds(BacktestPeriod.DEVELOPMENT)
    with pytest.raises(SplitViolation):
        guard.resolve(BacktestPeriod.FORWARD, start_ms=dev_start, end_ms=dev_start + 3_600_000)


def test_a_direct_test_period_resolve_still_raises_even_with_a_guard_also_used_for_forward():
    """Belt-and-suspenders: the same SplitGuard instance a paper tick uses for FORWARD still refuses TEST
    exactly as before - nothing about adding FORWARD weakened the existing sealed-test guard."""
    guard = SplitGuard(APP.splits)
    guard.resolve(BacktestPeriod.FORWARD, end_ms=guard.period_bounds(BacktestPeriod.TEST)[1] + 3_600_000)
    with pytest.raises(SealedAccessError):
        guard.resolve(BacktestPeriod.TEST)


def test_forward_start_is_contiguous_with_the_sealed_test_periods_end():
    """The real config: nothing between test.end and forward_start is ever silently skipped or double
    counted - the two periods are adjacent, matching docs/architecture.md's "Data periods" table."""
    guard = SplitGuard(APP.splits)
    _, test_end = guard.period_bounds(BacktestPeriod.TEST)
    assert to_ms(APP.splits.forward_start) == test_end  # real config fact, not a hardcoded assumption here
