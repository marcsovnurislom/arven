"""Two model families: a from-scratch numpy logistic regression, and a thin LightGBM adapter.

Logistic regression needs no new dependency (this project avoids them where reasonable - see
docs/current_state.md); LightGBM is the one approved Stage 6 dependency (decision D1), used only through
its public, deterministic training API - nothing here reaches into its internals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np


def _sigmoid(z: np.ndarray) -> np.ndarray:
    out = np.empty_like(z, dtype=np.float64)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


@dataclass(frozen=True, slots=True)
class LogisticRegressionModel:
    """Deterministic L2-regularised logistic regression, fit by Newton's method (IRLS). The intercept is
    never regularised. Converges in a handful of iterations for well-conditioned, standardised inputs."""

    weights: np.ndarray  # shape (n_features,)
    intercept: float
    feature_names: tuple[str, ...]
    l2: float
    n_iter: int

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        z = x @ self.weights + self.intercept
        return _sigmoid(z)


def fit_logistic_regression(
    x: np.ndarray, y: np.ndarray, feature_names: tuple[str, ...], l2: float, max_iter: int = 50, tol: float = 1e-10
) -> LogisticRegressionModel:
    """``x``: standardised (n_samples, n_features), no intercept column. ``y``: 0/1 labels."""
    n, p = x.shape
    if y.shape != (n,):
        raise ValueError("x and y must have matching sample counts")
    xa = np.hstack([np.ones((n, 1)), x])  # column 0 = intercept, never regularised
    beta = np.zeros(p + 1)
    reg = np.eye(p + 1) * l2
    reg[0, 0] = 0.0
    prev_ll = -math.inf
    n_iter = 0
    for n_iter in range(1, max_iter + 1):
        z = xa @ beta
        pr = _sigmoid(z)
        w = np.clip(pr * (1 - pr), 1e-10, None)
        grad = xa.T @ (y - pr) - reg @ beta
        hessian = -(xa.T * w) @ xa - reg
        try:
            delta = np.linalg.solve(hessian, grad)
        except np.linalg.LinAlgError:
            delta = np.linalg.lstsq(hessian, grad, rcond=None)[0]
        beta = beta - delta
        pr_clipped = np.clip(pr, 1e-12, 1 - 1e-12)
        ll = float(np.sum(y * np.log(pr_clipped) + (1 - y) * np.log(1 - pr_clipped)) - 0.5 * l2 * np.sum(beta[1:] ** 2))
        if abs(ll - prev_ll) < tol:
            break
        prev_ll = ll
    return LogisticRegressionModel(beta[1:].copy(), float(beta[0]), feature_names, l2, n_iter)


@dataclass(frozen=True, slots=True)
class LightGBMModel:
    """Stores the booster as its canonical text dump (``model_to_string()``), not the raw ``lgb.Booster``
    object: pickling a live ``Booster`` is not stable across a save/load round trip (its Python-level pickle
    state is reconstructed from this same string internally, so a freshly-trained booster and one reloaded
    from disk serialize to different bytes even though they predict identically) - this broke artifact-hash
    verification (a real bug this project's own tests caught) until fixed by hashing/storing the string
    directly, which *is* stable under pickling (it is plain text)."""

    model_str: str
    feature_names: tuple[str, ...]
    params: dict
    best_iteration: int

    @property
    def booster(self) -> lgb.Booster:
        return lgb.Booster(model_str=self.model_str)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self.booster.predict(x, num_iteration=self.best_iteration), dtype=np.float64)

    def feature_importance(self, importance_type: str = "gain") -> dict[str, float]:
        values = self.booster.feature_importance(importance_type=importance_type)
        return dict(zip(self.feature_names, (float(v) for v in values)))

    def shap_values(self, x: np.ndarray) -> np.ndarray:
        """Native Tree-SHAP contributions (no separate `shap` package needed); shape (n, n_features+1),
        last column is the expected-value bias term."""
        return np.asarray(self.booster.predict(x, pred_contrib=True, num_iteration=self.best_iteration))


def fit_lightgbm(
    x_train: np.ndarray, y_train: np.ndarray, x_valid: np.ndarray, y_valid: np.ndarray,
    feature_names: tuple[str, ...], params: dict, n_estimators_max: int, early_stopping_rounds: int, seed: int,
) -> LightGBMModel:
    n_pos = int(y_train.sum())
    n_neg = len(y_train) - n_pos
    scale_pos_weight = (n_neg / n_pos) if n_pos > 0 else 1.0
    full_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "verbosity": -1,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 1,
        "seed": seed,
        "bagging_seed": seed,
        "feature_fraction_seed": seed,
        "data_random_seed": seed,
        "scale_pos_weight": scale_pos_weight,
        **params,
    }
    train_set = lgb.Dataset(x_train, label=y_train, feature_name=list(feature_names), free_raw_data=False)
    valid_set = lgb.Dataset(x_valid, label=y_valid, feature_name=list(feature_names), reference=train_set, free_raw_data=False)
    booster = lgb.train(
        full_params, train_set, num_boost_round=n_estimators_max, valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False), lgb.log_evaluation(period=0)],
    )
    best_iter = booster.best_iteration or n_estimators_max
    return LightGBMModel(booster.model_to_string(), feature_names, dict(full_params), int(best_iter))
