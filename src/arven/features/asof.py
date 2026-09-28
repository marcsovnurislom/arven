"""Backward as-of alignment: the only way lower- and higher-frequency data are joined onto the decision grid.

For a decision time ``t`` the value taken from a source is that of the **last record with
``available_at <= t``**. A record can never be used before it was available, and a record that is too
old is *not* carried forward: it becomes NaN.
"""

from __future__ import annotations

import numpy as np


def _check_sorted(a: np.ndarray, what: str) -> None:
    if len(a) > 1 and np.any(np.diff(a) < 0):
        raise ValueError(f"{what} must be sorted in non-decreasing order")


def asof_index(available_at_ms: np.ndarray, t_ms: np.ndarray) -> np.ndarray:
    """Index of the last record with ``available_at <= t`` for each ``t`` (-1 if there is none)."""
    _check_sorted(available_at_ms, "available_at_ms")
    return np.searchsorted(available_at_ms, t_ms, side="right") - 1


def asof_join(
    available_at_ms: np.ndarray,
    values: np.ndarray,
    t_ms: np.ndarray,
    *,
    max_age_ms: int | None = None,
    event_time_ms: np.ndarray | None = None,
) -> np.ndarray:
    """Value of the last record available at each ``t``; NaN if none, or if it is older than ``max_age_ms``.

    Age is ``t - event_time`` (``event_time_ms`` defaults to ``available_at_ms``). The staleness limit is
    what stops a lost stream from silently repeating its last value.
    """
    if len(values) != len(available_at_ms):
        raise ValueError("values and available_at_ms must have equal length")
    idx = asof_index(available_at_ms, t_ms)
    ok = idx >= 0
    safe = np.where(ok, idx, 0)
    if max_age_ms is not None and len(available_at_ms):
        ref = available_at_ms if event_time_ms is None else event_time_ms
        ok &= (t_ms - ref[safe]) <= max_age_ms
    out = np.full(len(t_ms), np.nan)
    if len(values):
        out[ok] = values[safe[ok]]
    return out
