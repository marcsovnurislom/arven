"""Invariant checks on a built feature table (value ranges that must hold regardless of the market)."""

from __future__ import annotations

import numpy as np

from arven.features.builder import FeatureTable

# (how to match, pattern, lower bound, upper bound); bounds are inclusive, None = unbounded.
_BOUNDS: tuple[tuple[str, str, float | None, float | None], ...] = (
    ("contains", "_rsi", 0.0, 100.0),
    ("contains", "_adx", 0.0, 100.0),
    ("contains", "_taker_buy_ratio", 0.0, 1.0),
    ("contains", "_donchian_pos_", 0.0, 1.0),
    ("contains", "_upper_wick", 0.0, 1.0),
    ("contains", "_lower_wick", 0.0, 1.0),
    ("contains", "_body_ratio", -1.0, 1.0),
    ("contains", "_atr_pct", 0.0, None),
    ("contains", "_rel_volume", 0.0, None),
    ("contains", "_rel_trades", 0.0, None),
    ("contains", "_cc_vol_", 0.0, None),
    ("contains", "_parkinson_", 0.0, None),
    ("contains", "_rv_", 0.0, None),
    ("contains", "_bb_width", 0.0, None),
    ("exact", "fund_hours_to_next", 0.0, 24.0),
    ("exact", "oi_age_s", 0.0, None),
    ("exact", "oi_available", 0.0, 1.0),
    ("exact", "funding_available", 0.0, 1.0),
    ("exact", "feat_ready", 0.0, 1.0),
    ("prefix", "time_", -1.0, 1.0),
)


def _matches(kind: str, pattern: str, name: str) -> bool:
    if kind == "exact":
        return name == pattern
    if kind == "prefix":
        return name.startswith(pattern)
    return pattern in name


def invariant_violations(table: FeatureTable) -> list[str]:
    """Human-readable violations: non-finite values (must be NaN, never inf) and out-of-range values."""
    problems: list[str] = []
    for name, col in table.columns.items():
        if np.any(np.isinf(col)):
            problems.append(f"{name}: contains +/-inf")
        for kind, pattern, lo, hi in _BOUNDS:
            if _matches(kind, pattern, name):
                finite = col[np.isfinite(col)]
                if lo is not None and np.any(finite < lo):
                    problems.append(f"{name}: value below {lo} (min {finite.min():.6g})")
                if hi is not None and np.any(finite > hi):
                    problems.append(f"{name}: value above {hi} (max {finite.max():.6g})")
                break
    return problems
