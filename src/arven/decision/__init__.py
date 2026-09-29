"""Decision engine (Stage 5): regime gating + weighted vote -> a proposed action.

Combines the candidates from independent strategies with the current regime into one
:class:`~arven.decision.engine.ProposedDecision`. It never sees the portfolio (sizing and vetoing is the risk
engine's job) and never knows which strategy fired beyond bookkeeping for the explanation/log payload.
"""
