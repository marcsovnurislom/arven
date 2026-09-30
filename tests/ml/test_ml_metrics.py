"""Classification / probability-quality metrics: hand-computed cases."""

import math

import numpy as np
import pytest

from arven.ml.metrics import (
    brier_score,
    calibration_curve,
    expected_calibration_error,
    log_loss,
    pr_auc,
    precision_coverage_at_thresholds,
    roc_auc,
)


def test_log_loss_hand_case():
    y = np.array([1.0, 0.0])
    p = np.array([0.8, 0.2])
    expected = -(math.log(0.8) + math.log(0.8)) / 2
    assert log_loss(y, p) == pytest.approx(expected)


def test_log_loss_perfect_predictions_near_zero():
    y = np.array([1.0, 0.0, 1.0])
    p = np.array([1.0, 0.0, 1.0])
    assert log_loss(y, p) < 1e-10


def test_brier_score_hand_case():
    y = np.array([1.0, 0.0])
    p = np.array([0.9, 0.3])
    assert brier_score(y, p) == pytest.approx(((0.9 - 1) ** 2 + (0.3 - 0) ** 2) / 2)


def test_roc_auc_hand_case_perfect_separation():
    y = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    assert roc_auc(y, p) == pytest.approx(1.0)


def test_roc_auc_random_is_about_half():
    rng = np.random.default_rng(0)
    y = (rng.random(5000) < 0.5).astype(float)
    p = rng.random(5000)
    assert roc_auc(y, p) == pytest.approx(0.5, abs=0.03)


def test_roc_auc_handles_ties_by_averaging_ranks():
    y = np.array([0.0, 1.0, 0.0, 1.0])
    p = np.array([0.5, 0.5, 0.5, 0.5])
    assert roc_auc(y, p) == pytest.approx(0.5)


def test_roc_auc_none_for_single_class():
    assert roc_auc(np.zeros(5), np.array([0.1, 0.2, 0.3, 0.4, 0.5])) is None
    assert roc_auc(np.ones(5), np.array([0.1, 0.2, 0.3, 0.4, 0.5])) is None


def test_pr_auc_perfect_separation_is_one():
    y = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    assert pr_auc(y, p) == pytest.approx(1.0)


def test_pr_auc_none_without_positives():
    assert pr_auc(np.zeros(5), np.array([0.1, 0.2, 0.3, 0.4, 0.5])) is None


def test_expected_calibration_error_zero_when_perfectly_calibrated():
    rng = np.random.default_rng(1)
    p = rng.random(20000)
    y = (rng.random(20000) < p).astype(float)
    assert expected_calibration_error(y, p, n_bins=10) < 0.02


def test_calibration_curve_bin_counts_sum_to_total():
    y = np.array([1.0, 0.0, 1.0, 0.0, 1.0])
    p = np.array([0.05, 0.15, 0.55, 0.65, 0.95])
    rows = calibration_curve(y, p, n_bins=10)
    assert sum(r["n"] for r in rows) == 5


def test_precision_coverage_at_thresholds_hand_case():
    y = np.array([1.0, 1.0, 0.0, 0.0])
    p = np.array([0.9, 0.6, 0.6, 0.1])
    rows = precision_coverage_at_thresholds(y, p, (0.5, 0.8))
    row_50 = next(r for r in rows if r["threshold"] == 0.5)
    assert row_50["n_taken"] == 3 and row_50["precision"] == pytest.approx(2 / 3)
    row_80 = next(r for r in rows if r["threshold"] == 0.8)
    assert row_80["n_taken"] == 1 and row_80["precision"] == pytest.approx(1.0)


def test_precision_coverage_none_when_nothing_taken():
    y, p = np.array([1.0, 0.0]), np.array([0.1, 0.2])
    rows = precision_coverage_at_thresholds(y, p, (0.9,))
    assert rows[0]["n_taken"] == 0 and rows[0]["precision"] is None
