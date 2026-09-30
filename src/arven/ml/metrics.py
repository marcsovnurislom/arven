"""Classification / probability-quality metrics, pure numpy. Never called on the sealed test period during
development (callers pass only development/validation-derived arrays; enforced at the orchestration layer,
not here, since these are pure functions with no notion of a period)."""

from __future__ import annotations

import numpy as np


def log_loss(y: np.ndarray, p: np.ndarray, eps: float = 1e-12) -> float:
    pc = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc)))


def brier_score(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def roc_auc(y: np.ndarray, p: np.ndarray) -> float | None:
    """Rank-based AUC (Mann-Whitney U / concordance); ``None`` if only one class is present."""
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(p, kind="stable")
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks for ties
    sorted_p = p[order]
    i = 0
    while i < len(sorted_p):
        j = i
        while j + 1 < len(sorted_p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        if j > i:
            avg = ranks[order[i : j + 1]].mean()
            ranks[order[i : j + 1]] = avg
        i = j + 1
    sum_ranks_pos = ranks[y == 1].sum()
    auc = (sum_ranks_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


def pr_auc(y: np.ndarray, p: np.ndarray) -> float | None:
    """Area under the precision-recall curve via trapezoidal integration over sorted thresholds."""
    n_pos = int(y.sum())
    if n_pos == 0:
        return None
    order = np.argsort(-p, kind="stable")
    y_sorted = y[order]
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / n_pos
    recall = np.concatenate(([0.0], recall))
    precision = np.concatenate(([precision[0] if len(precision) else 1.0], precision))
    return float(np.trapezoid(precision, recall))


def expected_calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi) if i < n_bins - 1 else (p >= lo) & (p <= hi)
        if not mask.any():
            continue
        conf = float(p[mask].mean())
        acc = float(y[mask].mean())
        ece += (mask.sum() / n) * abs(acc - conf)
    return float(ece)


def calibration_curve(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> list[dict[str, float | int]]:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows: list[dict[str, float | int]] = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi) if i < n_bins - 1 else (p >= lo) & (p <= hi)
        n = int(mask.sum())
        rows.append({
            "bin_lo": float(lo), "bin_hi": float(hi), "n": n,
            "mean_predicted": float(p[mask].mean()) if n else float("nan"),
            "observed_rate": float(y[mask].mean()) if n else float("nan"),
        })
    return rows


def precision_coverage_at_thresholds(y: np.ndarray, p: np.ndarray, thresholds: tuple[float, ...]) -> list[dict[str, float | int]]:
    rows = []
    n = len(y)
    for th in thresholds:
        mask = p >= th
        taken = int(mask.sum())
        rows.append({
            "threshold": th, "coverage": taken / n if n else 0.0, "n_taken": taken,
            "precision": float(y[mask].mean()) if taken else None,
        })
    return rows
