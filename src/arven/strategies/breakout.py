"""Breakout strategy (architecture #3: volatility breakout — range compression, then expansion).

A squeeze is detected causally: Bollinger band width (``h1_bb_width``) must have been at or below a low
percentile of its own trailing window at some point within the recent lookback (the percentile threshold is
computed from the window *excluding* the current bar, so today's value never sets its own bar). The trigger
is price reaching a Donchian-channel extreme *now*. Direction follows the break; there is no separate trend
filter (regime gating in ``config/strategies.yaml`` restricts this to NORMAL/HIGH volatility instead).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from arven.backtest.provider import FeatureView
from arven.core.strategies_config import BreakoutConfig
from arven.strategies.base import CandidateSignal

STRATEGY_ID = "breakout"


@dataclass(frozen=True, slots=True)
class BreakoutStrategy:
    cfg: BreakoutConfig
    strategy_id: str = STRATEGY_ID

    @property
    def gate(self) -> BreakoutConfig:
        return self.cfg

    def evaluate(self, view: FeatureView, t_ms: int) -> CandidateSignal | None:
        c = self.cfg
        width_hist = view.history("h1_bb_width", c.bb_width_window_bars, t_ms)
        if len(width_hist) < c.bb_width_window_bars or not np.isfinite(width_hist).all():
            return None  # not enough warm history yet for a meaningful percentile
        donchian = view.value(c.donchian_feature, t_ms)
        atr_pct = view.value("h1_atr_pct", t_ms)
        if not (math.isfinite(donchian) and math.isfinite(atr_pct)):
            return None

        if donchian >= c.breakout_upper:
            direction = 1
        elif donchian <= c.breakout_lower:
            direction = -1
        else:
            return None

        reference = width_hist[:-1]  # threshold from history strictly before now: today can't set its own bar
        threshold = float(np.percentile(reference, c.compression_percentile))
        recent = width_hist[-1 - c.compression_lookback_bars : -1]  # the lookback window, excluding today
        if len(recent) == 0 or float(recent.min()) >= threshold:
            return None  # no squeeze (strictly below the threshold) observed recently: not a compression breakout

        span = (1.0 - c.breakout_upper) if direction > 0 else c.breakout_lower
        edge = (donchian - c.breakout_upper) if direction > 0 else (c.breakout_lower - donchian)
        strength = max(0.0, min(1.0, edge / span)) if span > 0 else 1.0
        reasons = (
            f"Donchian position {donchian:.3f} breaks {'above' if direction > 0 else 'below'} the channel",
            f"bb_width was <= p{c.compression_percentile:.0f} ({threshold:.5f}) within the last {c.compression_lookback_bars} bars",
        )
        return CandidateSignal(
            STRATEGY_ID, direction, strength, c.stop_atr_mult * atr_pct, c.take_profit_atr_mult * atr_pct,
            c.max_holding_minutes, reasons,
        )
