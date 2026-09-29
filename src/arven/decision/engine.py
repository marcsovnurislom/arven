"""Combine strategy candidates into one proposed action.

``DecisionEngine.decide`` implements docs/architecture.md section 13 steps 1-3, 5, 6 (step 4, the ML filter,
is Stage 6 and does not exist yet — omitted, not stubbed, so nothing pretends to gate on a probability that
was never computed). The engine never sees the portfolio: sizing and vetoing are the risk engine's job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arven.core.types import Action
from arven.regime.detector import Regime
from arven.strategies.base import CandidateSignal, RegimeGate


@dataclass(frozen=True, slots=True)
class ProposedDecision:
    t_ms: int
    action: Action
    score: float  # signed weighted vote; 0.0 when the action is NO_TRADE
    confidence: float  # |score| / (sum of all configured weights), in [0, 1]
    contributing: tuple[str, ...]  # strategy_ids on the winning side, post-gating
    gated_out: tuple[str, ...]  # strategy_ids whose candidate was filtered out by the regime gate
    reasons: tuple[str, ...]
    regime: Regime
    stop_pct: float | None  # weighted average of the winning candidates' hints; None for NO_TRADE
    take_profit_pct: float | None
    max_holding_minutes: int | None
    all_candidates: tuple[CandidateSignal, ...]  # every candidate before gating (for logging/explanation)


def _no_trade(t_ms: int, regime: Regime, candidates: tuple[CandidateSignal, ...], gated_out: tuple[str, ...], reason: str) -> ProposedDecision:
    return ProposedDecision(t_ms, Action.NO_TRADE, 0.0, 0.0, (), gated_out, (reason,), regime, None, None, None, candidates)


class DecisionEngine:
    def __init__(self, weights: dict[str, float], gates: dict[str, RegimeGate], decision_threshold: float, conflict_threshold: float) -> None:
        self.weights = dict(weights)
        self.gates = dict(gates)
        self.decision_threshold = decision_threshold
        self.conflict_threshold = conflict_threshold
        self._max_score = sum(self.weights.values())

    def _gate_ok(self, c: CandidateSignal, regime: Regime) -> bool:
        gate = self.gates[c.strategy_id]
        if gate.allowed_trends is not None and regime.trend.value not in gate.allowed_trends:
            return False
        if gate.allowed_vols is not None and regime.vol.value not in gate.allowed_vols:
            return False
        return not (gate.require_not_stress and regime.stress)

    def decide(self, t_ms: int, candidates: list[CandidateSignal], regime: Regime) -> ProposedDecision:
        candidates_t = tuple(candidates)
        allowed = [c for c in candidates_t if self._gate_ok(c, regime)]
        allowed_ids = {c.strategy_id for c in allowed}
        gated_out = tuple(c.strategy_id for c in candidates_t if c.strategy_id not in allowed_ids)
        if not allowed:
            return _no_trade(t_ms, regime, candidates_t, gated_out, "no candidate passed the regime gate")

        pos_mass = sum(self.weights[c.strategy_id] * c.strength for c in allowed if c.direction > 0)
        neg_mass = sum(self.weights[c.strategy_id] * c.strength for c in allowed if c.direction < 0)
        score = pos_mass - neg_mass

        if pos_mass >= self.conflict_threshold and neg_mass >= self.conflict_threshold:
            return _no_trade(t_ms, regime, candidates_t, gated_out, f"conflict: pos={pos_mass:.3f} neg={neg_mass:.3f} both >= {self.conflict_threshold:.3f}")
        if abs(score) < self.decision_threshold:
            return _no_trade(t_ms, regime, candidates_t, gated_out, f"|score|={abs(score):.3f} < threshold {self.decision_threshold:.3f}")

        direction = 1 if score > 0 else -1
        winners = [c for c in allowed if c.direction == direction]
        w = [self.weights[c.strategy_id] * c.strength for c in winners]
        total_w = sum(w)
        stop_pct = sum(wi * c.stop_pct for wi, c in zip(w, winners)) / total_w
        take_profit_pct = sum(wi * c.take_profit_pct for wi, c in zip(w, winners)) / total_w
        holdings = [c.max_holding_minutes for c in winners if c.max_holding_minutes is not None]
        max_holding = min(holdings) if holdings else None  # the most conservative (shortest) declared holding cap
        confidence = max(0.0, min(1.0, abs(score) / self._max_score)) if self._max_score > 0 else 0.0
        reasons = tuple(f"{c.strategy_id}: {r}" for c in winners for r in c.reasons)
        action = Action.LONG if direction > 0 else Action.SHORT
        return ProposedDecision(
            t_ms, action, score, confidence, tuple(c.strategy_id for c in winners), gated_out, reasons,
            regime, stop_pct, take_profit_pct, max_holding, candidates_t,
        )
