"""Isotonic probability calibration via the Pool-Adjacent-Violators Algorithm (PAVA), pure numpy
(decision D6). Fit on a fold's own held-out validation block, never on the data the base model trained on
and never on the sealed test period.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _pava(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Weighted isotonic (non-decreasing) regression of ``y`` (already sorted by x). Standard stack-based
    PAVA: each stack entry is ``[level, weight, start_index]``; adjacent entries that violate monotonicity
    are merged (weighted mean) until the stack is non-decreasing."""
    n = len(y)
    stack: list[list[float]] = []
    for i in range(n):
        stack.append([float(y[i]), float(w[i]), i])
        while len(stack) > 1 and stack[-2][0] > stack[-1][0]:
            v2, w2, _s2 = stack.pop()
            v1, w1, s1 = stack.pop()
            mw = w1 + w2
            stack.append([(v1 * w1 + v2 * w2) / mw, mw, s1])
    out = np.empty(n, dtype=np.float64)
    end = n
    for level, _weight, start in reversed(stack):
        out[start:end] = level
        end = start
    return out


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    x_thresholds: np.ndarray  # sorted unique raw scores
    y_levels: np.ndarray  # matching calibrated probabilities (non-decreasing)

    def predict(self, raw_scores: np.ndarray) -> np.ndarray:
        return np.clip(np.interp(raw_scores, self.x_thresholds, self.y_levels), 0.0, 1.0)


def fit_isotonic(raw_scores: np.ndarray, labels: np.ndarray) -> IsotonicCalibrator:
    if len(raw_scores) != len(labels):
        raise ValueError("raw_scores and labels must have equal length")
    if len(raw_scores) == 0:
        raise ValueError("cannot fit a calibrator on zero samples")
    order = np.argsort(raw_scores, kind="stable")
    xs = raw_scores[order]
    ys = labels[order].astype(np.float64)
    weights = np.ones_like(ys)
    fitted = _pava(ys, weights)
    # Deduplicate x for interpolation (PAVA can tie many x's to one block level; keep first/last per block).
    x_uniq, first_idx = np.unique(xs, return_index=True)
    y_uniq = fitted[first_idx]
    return IsotonicCalibrator(x_uniq, y_uniq)
