"""The forward review rule: what the live record of a strategy says so far, stated with its uncertainty.

Fixed on 2026-10-16 (``config/live.yaml`` ``forward_review``), before any further forward data. The thresholds
are the textbook ones (at least 30 closed signals, a two-sided 95 % normal-approximation confidence interval for
the mean net R per signal); they were not tuned to any strategy's numbers. On 2026-10-16 those numbers were
already visible (S6 -23.5 R on 166 closed signals), so this is a monitoring rule, not a hypothesis test.

- ``too_few``: fewer than ``min_closed`` closed signals; nothing can be said yet.
- ``losing``: the whole interval is below 0. The record is evidence that the strategy loses under these costs.
- ``positive``: the whole interval is above 0. This is not ``VALIDATED`` on its own (the grading gate also needs
  walk-forward and sealed-test evidence), but it is worth a closer look.
- ``inconclusive``: the interval contains 0.

The rule only *flags*. It never switches a strategy off, which stays the owner's decision (``enabled: false`` in
``config/live.yaml``). Signals carry their grade (``EXPERIMENTAL``) either way.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

Z95 = 1.959963984540054


def max_drawdown_r(rs: Sequence[float]) -> float:
    """Largest peak-to-trough fall of the cumulative R curve, in R (>= 0), in the given (closing-time) order."""
    peak = cum = worst = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return worst


def forward_review(rs: Sequence[float], min_closed: int = 30) -> dict[str, Any]:
    """``rs``: net R of the closed signals in closing-time order."""
    n = len(rs)
    out: dict[str, Any] = {"n": n, "min_closed": min_closed, "mean_r": None, "ci_low": None, "ci_high": None,
                           "profit_factor": None, "max_dd_r": max_drawdown_r(rs) if n else None}
    if n:
        mean = sum(rs) / n
        gains, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
        out["mean_r"] = mean
        out["profit_factor"] = gains / losses if losses > 0 else None
        if n >= 2:
            sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1))
            half = Z95 * sd / math.sqrt(n)
            out["ci_low"], out["ci_high"] = mean - half, mean + half
    if n < min_closed or out["ci_low"] is None:
        verdict = "too_few"
    elif out["ci_high"] < 0:
        verdict = "losing"
    elif out["ci_low"] > 0:
        verdict = "positive"
    else:
        verdict = "inconclusive"
    out["verdict"] = verdict
    return out


__all__ = ["Z95", "forward_review", "max_drawdown_r"]
