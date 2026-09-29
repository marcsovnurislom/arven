"""Three independent, rule-based strategies (Stage 5).

Each strategy reads only causal Stage 3 features (never the portfolio, other strategies, or the regime
label) and returns a :class:`~arven.strategies.base.CandidateSignal` or ``None``. Regime gating and combining
candidates into one decision is the decision layer's job (``arven.decision``), not the strategy's.
"""

from arven.strategies.base import CandidateSignal, Strategy
from arven.strategies.breakout import BreakoutStrategy
from arven.strategies.mean_reversion import MeanReversionStrategy
from arven.strategies.trend_momentum import TrendMomentumStrategy

__all__ = ["BreakoutStrategy", "CandidateSignal", "MeanReversionStrategy", "Strategy", "TrendMomentumStrategy"]
