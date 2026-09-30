"""Isotonic calibration (PAVA): hand-computed cases and monotonicity properties."""

import numpy as np
import pytest

from arven.ml.calibration import _pava, fit_isotonic


def test_pava_hand_case_single_violation():
    out = _pava(np.array([1.0, 0.0, 1.0, 1.0]), np.ones(4))
    assert out.tolist() == [0.5, 0.5, 1.0, 1.0]


def test_pava_already_monotone_is_unchanged():
    y = np.array([0.1, 0.3, 0.3, 0.8])
    out = _pava(y, np.ones(4))
    assert np.allclose(out, y)


def test_pava_weighted_merge():
    # 1.0 (weight 3) > 0.0 (weight 1): a violation, weighted-merged to (1*3 + 0*1)/4 = 0.75
    out = _pava(np.array([1.0, 0.0]), np.array([3.0, 1.0]))
    assert out.tolist() == pytest.approx([0.75, 0.75])


def test_pava_all_decreasing_collapses_to_the_mean():
    y = np.array([3.0, 2.0, 1.0, 0.0])
    out = _pava(y, np.ones(4))
    assert np.allclose(out, y.mean())


def test_fit_isotonic_predictions_are_monotone_and_bounded():
    rng = np.random.default_rng(0)
    x = rng.normal(size=300)
    y = (rng.random(300) < 1 / (1 + np.exp(-x))).astype(float)
    cal = fit_isotonic(x, y)
    grid = np.linspace(x.min() - 1, x.max() + 1, 200)
    pred = cal.predict(grid)
    assert np.all(np.diff(pred) >= -1e-9)
    assert np.all((pred >= 0) & (pred <= 1))


def test_fit_isotonic_extrapolates_by_clamping():
    cal = fit_isotonic(np.array([0.0, 1.0, 2.0]), np.array([0.0, 0.5, 1.0]))
    assert cal.predict(np.array([-10.0]))[0] == pytest.approx(cal.predict(np.array([0.0]))[0])
    assert cal.predict(np.array([10.0]))[0] == pytest.approx(cal.predict(np.array([2.0]))[0])


def test_fit_isotonic_rejects_mismatched_or_empty_input():
    with pytest.raises(ValueError):
        fit_isotonic(np.array([1.0, 2.0]), np.array([1.0]))
    with pytest.raises(ValueError):
        fit_isotonic(np.array([]), np.array([]))


def test_fit_isotonic_is_deterministic():
    rng = np.random.default_rng(3)
    x, y = rng.normal(size=200), (rng.random(200) < 0.4).astype(float)
    c1, c2 = fit_isotonic(x, y), fit_isotonic(x, y)
    assert np.array_equal(c1.y_levels, c2.y_levels) and np.array_equal(c1.x_thresholds, c2.x_thresholds)
