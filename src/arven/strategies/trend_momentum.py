"""Trend/Momentum strategy (architecture #1: EMA crossover on 1h, ADX-based 4h trend filter).

Direction comes from the 1h EMA(fast) vs EMA(slow) relationship (derived from the two ``ema_dist`` features,
since ``dist_fast - dist_slow = ln(EMA_slow / EMA_fast)``), confirmed by a 4h ADX trend filter (ADX above
threshold, and the 4h EMA slope's sign must agree with the crossover direction), and optionally confirmed by
MACD histogram sign; entries against an already-extreme RSI are blocked (no chasing an exhausted move).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arven.backtest.provider import FeatureView
from arven.core.strategies_config import TrendMomentumConfig
from arven.strategies.base import CandidateSignal

STRATEGY_ID = "trend_momentum"

_REQUIRED = ("h1_ema_dist_{fast}", "h1_ema_dist_{slow}", "h4_adx", "h4_ema_slope", "h1_macd_hist", "h1_rsi", "h1_atr_pct")


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


@dataclass(frozen=True, slots=True)
class TrendMomentumStrategy:
    cfg: TrendMomentumConfig
    strategy_id: str = STRATEGY_ID

    @property
    def gate(self) -> TrendMomentumConfig:
        return self.cfg

    def evaluate(self, view: FeatureView, t_ms: int) -> CandidateSignal | None:
        c = self.cfg
        names = [n.format(fast=c.ema_fast, slow=c.ema_slow) for n in _REQUIRED]
        values = {n: view.value(n, t_ms) for n in names}
        if not all(math.isfinite(v) for v in values.values()):
            return None
        dist_fast, dist_slow = values[names[0]], values[names[1]]
        adx4, slope4 = values["h4_adx"], values["h4_ema_slope"]
        macd, rsi, atr_pct = values["h1_macd_hist"], values["h1_rsi"], values["h1_atr_pct"]

        # dist_fast - dist_slow > 0 means EMA_slow > EMA_fast (fast below slow, bearish); < 0 means bullish.
        direction = -_sign(dist_fast - dist_slow)
        if direction == 0:
            return None
        if adx4 < c.adx_4h_threshold or _sign(slope4) != direction:
            return None
        if c.require_macd_confirm and _sign(macd) != direction:
            return None
        if direction > 0 and rsi >= c.rsi_overbought_block:
            return None
        if direction < 0 and rsi <= c.rsi_oversold_block:
            return None

        strength = max(0.0, min(1.0, adx4 / c.adx_strength_scale))
        reasons = (
            f"1h EMA{c.ema_fast}/{c.ema_slow} cross {'bullish' if direction > 0 else 'bearish'}",
            f"4h ADX {adx4:.1f} >= {c.adx_4h_threshold:.1f}, slope agrees",
            f"1h MACD hist {'confirms' if c.require_macd_confirm else 'not checked'}",
            f"1h RSI {rsi:.1f} not blocking",
        )
        return CandidateSignal(
            STRATEGY_ID, direction, strength, c.stop_atr_mult * atr_pct, c.take_profit_atr_mult * atr_pct,
            c.max_holding_minutes, reasons,
        )
