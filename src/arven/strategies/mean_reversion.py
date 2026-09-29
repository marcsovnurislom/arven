"""Mean-reversion strategy (architecture #2: Bollinger/RSI extremes, only in RANGE).

Contrarian: enters against a Bollinger z-score extreme, confirmed by RSI also being extreme in the same
direction. "Only in RANGE" is regime gating (``allowed_trends: [NO_TREND]`` in ``config/strategies.yaml``),
applied by the decision engine — this strategy itself never looks at the regime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arven.backtest.provider import FeatureView
from arven.core.strategies_config import MeanReversionConfig
from arven.strategies.base import CandidateSignal

STRATEGY_ID = "mean_reversion"


@dataclass(frozen=True, slots=True)
class MeanReversionStrategy:
    cfg: MeanReversionConfig
    strategy_id: str = STRATEGY_ID

    @property
    def gate(self) -> MeanReversionConfig:
        return self.cfg

    def evaluate(self, view: FeatureView, t_ms: int) -> CandidateSignal | None:
        c = self.cfg
        z, rsi, atr_pct = view.value("h1_bb_z", t_ms), view.value("h1_rsi", t_ms), view.value("h1_atr_pct", t_ms)
        if not all(math.isfinite(v) for v in (z, rsi, atr_pct)):
            return None

        if z <= -c.bb_z_threshold and rsi <= c.rsi_oversold_confirm:
            direction = 1  # price too low vs its band and RSI agrees: buy the dip
        elif z >= c.bb_z_threshold and rsi >= c.rsi_overbought_confirm:
            direction = -1  # price too high, RSI agrees: sell the rip
        else:
            return None

        strength = max(0.0, min(1.0, abs(z) / c.bb_z_strength_scale))
        reasons = (
            f"Bollinger z {z:.2f} beyond +/-{c.bb_z_threshold:.1f}",
            f"1h RSI {rsi:.1f} confirms",
        )
        return CandidateSignal(
            STRATEGY_ID, direction, strength, c.stop_atr_mult * atr_pct, c.take_profit_atr_mult * atr_pct,
            c.max_holding_minutes, reasons,
        )
