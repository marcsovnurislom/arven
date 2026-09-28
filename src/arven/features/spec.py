"""Feature specification: what every registered feature declares about itself."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str  # returns | volatility | trend | momentum | volume | candle | funding | open_interest | time | quality
    source: str  # 5m | 15m | 1h | 4h | funding | oi | time | derived
    # Number of source records (bars, fundings, hours) needed before the first non-NaN value on clean
    # data: the first valid index of the feature on its source grid is ``warmup_bars - 1``.
    warmup_bars: int
    # Required features must all be finite for ``feat_ready`` to be 1. Optional ones (open interest,
    # whose history starts in 2020-09) may be NaN without making the row unusable.
    required: bool
    description: str
