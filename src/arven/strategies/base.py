"""The strategy contract.

A strategy maps ``features(t)`` to a :class:`CandidateSignal` or ``None``. It sees only the causal
:class:`~arven.backtest.provider.FeatureView` (Stage 3 features up to and including ``t``) — never the
portfolio, never other strategies, never the regime label. Regime *gating* (whether a strategy's candidate is
allowed to count at all) is config declared here (``allowed_trends``/``allowed_vols``/``require_not_stress``)
and applied by the decision engine, not by the strategy itself: this keeps regime detection, strategy logic
and combination logic in three independent, separately testable places.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from arven.backtest.provider import FeatureView


@dataclass(frozen=True, slots=True)
class CandidateSignal:
    strategy_id: str
    direction: int  # +1 long, -1 short (never 0: a strategy returns None instead of a flat candidate)
    strength: float  # in [0, 1]
    stop_pct: float  # > 0, fraction of the fill price
    take_profit_pct: float  # > 0
    max_holding_minutes: int | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError("direction must be +1 or -1")
        if not (math.isfinite(self.strength) and 0.0 <= self.strength <= 1.0):
            raise ValueError("strength must be finite and in [0, 1]")
        if not (math.isfinite(self.stop_pct) and self.stop_pct > 0):
            raise ValueError("stop_pct must be finite and positive")
        if not (math.isfinite(self.take_profit_pct) and self.take_profit_pct > 0):
            raise ValueError("take_profit_pct must be finite and positive")


class RegimeGate(Protocol):
    """The subset of a strategy's config the decision engine reads for regime gating."""

    allowed_trends: tuple[str, ...] | None
    allowed_vols: tuple[str, ...] | None
    require_not_stress: bool


class Strategy(Protocol):
    strategy_id: str
    gate: RegimeGate

    def evaluate(self, view: FeatureView, t_ms: int) -> CandidateSignal | None: ...
