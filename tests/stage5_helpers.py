"""A tiny, exact-value ``FeatureView`` builder for Stage 5 unit tests.

Regime/strategy/decision/risk tests need precise control over individual feature values (to hit specific
rule branches), not a realistic price path — so instead of running the full Stage 3 builder, this constructs
a :class:`~arven.backtest.provider.FeatureView` directly from named overrides, using the *real* Stage 3
column names (from the real registry) so a typo or a renamed column fails the test rather than silently
reading NaN.
"""

from __future__ import annotations

import numpy as np

from arven.backtest.clock import HOUR_MS, SimulationClock
from arven.backtest.provider import FeatureView
from arven.core.features_config import load_features_config
from arven.features.registry import build_registry

T0 = 1_609_718_400_000  # 2021-01-04 00:00 UTC (matches tests/bt_helpers.T0)

_SPECS = build_registry(load_features_config())
NAMES = tuple(s.name for s in _SPECS)
_COL = {n: i for i, n in enumerate(NAMES)}


def view_rows(rows: list[dict[str, float]], start_ms: int = T0) -> tuple[FeatureView, int]:
    """A FeatureView over ``len(rows)`` hourly rows; unset columns are NaN. Returns ``(view, t_ms_of_last_row)``."""
    n = len(rows)
    t = start_ms + np.arange(n, dtype=np.int64) * HOUR_MS
    values = np.full((n, len(NAMES)), np.nan)
    for i, row in enumerate(rows):
        for name, v in row.items():
            if name not in _COL:
                raise KeyError(f"{name!r} is not a real Stage 3 feature column")
            values[i, _COL[name]] = v
    clock = SimulationClock(t)
    for _ in range(n):
        clock.advance()
    return FeatureView(t, NAMES, values, clock, None), int(t[-1])


def single_row(overrides: dict[str, float], start_ms: int = T0) -> tuple[FeatureView, int]:
    """A one-row FeatureView (for rules that only need "now")."""
    return view_rows([overrides], start_ms)


def constant_rows(n: int, overrides: dict[str, float], start_ms: int = T0) -> tuple[FeatureView, int]:
    """``n`` identical rows (for history-based rules, e.g. the breakout strategy's compression window)."""
    return view_rows([dict(overrides) for _ in range(n)], start_ms)
