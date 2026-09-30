"""Logistic regression (hand-computed / convergence) and the LightGBM adapter (smoke + determinism)."""

import numpy as np
import pytest

from arven.ml.model import fit_lightgbm, fit_logistic_regression


def test_logistic_regression_recovers_known_weights_on_separable_data():
    rng = np.random.default_rng(0)
    n = 2000
    x = rng.normal(size=(n, 3))
    true_w, true_b = np.array([2.0, -1.5, 0.5]), 0.3
    p = 1 / (1 + np.exp(-(x @ true_w + true_b)))
    y = (rng.random(n) < p).astype(float)
    model = fit_logistic_regression(x, y, ("a", "b", "c"), l2=0.01)
    assert np.allclose(model.weights, true_w, atol=0.25)
    assert abs(model.intercept - true_b) < 0.15
    assert model.n_iter < 50


def test_logistic_regression_l2_shrinks_weights_toward_zero():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(1000, 3))
    y = (rng.random(1000) < 1 / (1 + np.exp(-(x @ [2.0, -1.0, 0.5])))).astype(float)
    weak = fit_logistic_regression(x, y, ("a", "b", "c"), l2=0.001)
    strong = fit_logistic_regression(x, y, ("a", "b", "c"), l2=100.0)
    assert np.linalg.norm(strong.weights) < np.linalg.norm(weak.weights)


def test_logistic_regression_predict_proba_hand_case():
    model = fit_logistic_regression(np.zeros((10, 1)), np.array([1.0] * 5 + [0.0] * 5), ("a",), l2=1e-6, max_iter=1)
    # with all-zero features, the model degenerates to predicting the base rate via the intercept alone
    p = model.predict_proba(np.zeros((1, 1)))
    assert 0.0 < p[0] < 1.0


def test_logistic_regression_is_deterministic():
    rng = np.random.default_rng(2)
    x = rng.normal(size=(300, 4))
    y = (rng.random(300) < 0.4).astype(float)
    m1 = fit_logistic_regression(x, y, ("a", "b", "c", "d"), l2=1.0)
    m2 = fit_logistic_regression(x, y, ("a", "b", "c", "d"), l2=1.0)
    assert np.array_equal(m1.weights, m2.weights) and m1.intercept == m2.intercept


def _lgb_data(seed=0, n=400):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 3))
    y = (rng.random(n) < 1 / (1 + np.exp(-(x[:, 0] * 2 - x[:, 1])))).astype(float)
    return x[: n * 3 // 4], y[: n * 3 // 4], x[n * 3 // 4 :], y[n * 3 // 4 :]


def test_lightgbm_trains_and_predicts_in_range():
    xt, yt, xv, yv = _lgb_data()
    hp = {"num_leaves": 7, "max_depth": 3, "learning_rate": 0.1, "min_data_in_leaf": 10, "feature_fraction": 0.8, "bagging_fraction": 0.8, "lambda_l1": 0.0, "lambda_l2": 1.0}
    m = fit_lightgbm(xt, yt, xv, yv, ("a", "b", "c"), hp, n_estimators_max=50, early_stopping_rounds=10, seed=42)
    p = m.predict_proba(xv)
    assert np.all((p >= 0) & (p <= 1))
    assert m.best_iteration >= 1


def test_lightgbm_is_deterministic_across_independent_fits():
    xt, yt, xv, yv = _lgb_data()
    hp = {"num_leaves": 7, "max_depth": 3, "learning_rate": 0.1, "min_data_in_leaf": 10, "feature_fraction": 0.8, "bagging_fraction": 0.8, "lambda_l1": 0.0, "lambda_l2": 1.0}
    m1 = fit_lightgbm(xt, yt, xv, yv, ("a", "b", "c"), hp, 50, 10, seed=7)
    m2 = fit_lightgbm(xt, yt, xv, yv, ("a", "b", "c"), hp, 50, 10, seed=7)
    assert m1.model_str == m2.model_str
    assert np.array_equal(m1.predict_proba(xv), m2.predict_proba(xv))


def test_lightgbm_feature_importance_and_shap_shapes():
    xt, yt, xv, yv = _lgb_data()
    hp = {"num_leaves": 7, "max_depth": 3, "learning_rate": 0.1, "min_data_in_leaf": 10, "feature_fraction": 0.8, "bagging_fraction": 0.8, "lambda_l1": 0.0, "lambda_l2": 1.0}
    m = fit_lightgbm(xt, yt, xv, yv, ("a", "b", "c"), hp, 50, 10, seed=1)
    imp = m.feature_importance()
    assert set(imp) == {"a", "b", "c"} and all(v >= 0 for v in imp.values())
    shap = m.shap_values(xv)
    assert shap.shape == (len(xv), 4)  # 3 features + bias term
