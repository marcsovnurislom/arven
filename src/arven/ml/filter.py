"""The meta-filter: the only place a trained model touches a live decision.

``MetaFilter.apply`` may only pass a :class:`~arven.decision.engine.ProposedDecision` through unchanged, or
downgrade it to ``NO_TRADE``. It never creates a trade, never flips a direction, never changes sizing or
risk parameters, and never sees the portfolio (its signature has no portfolio argument - mirroring
``DecisionEngine.decide``'s own portfolio-blindness, enforced by the same kind of static test). The
downstream :class:`~arven.risk.engine.RiskEngine` runs exactly as it does today, on whatever
``ProposedDecision`` comes out of here - it cannot be bypassed because it never knows the filter ran.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from arven.backtest.provider import FeatureView
from arven.decision.engine import ProposedDecision
from arven.ml.artifact import ModelArtifact
from arven.ml.dataset import CONTEXT_COLUMNS, build_context_vector

import numpy as np


def build_row(view: FeatureView, proposed: ProposedDecision, feature_names: tuple[str, ...]) -> np.ndarray:
    """The same encoding ``arven.ml.dataset.build_dataset`` uses, built from a live decision instead of a
    historical replay - via the single shared :func:`arven.ml.dataset.build_context_vector` helper, so
    training and live inference can never silently diverge (fixes the Stage 6 pre-commit audit's train/serve
    skew finding: this now reads ``proposed.stop_pct``/``take_profit_pct``/``max_holding_minutes`` - the raw,
    pre-``RiskEngine`` values - which is exactly what is available here, since ``MetaFilter`` runs strictly
    before ``RiskEngine`` and never receives a risk-bounded ``Signal``)."""
    row = view.row(proposed.t_ms)
    context = dict(zip(CONTEXT_COLUMNS, build_context_vector(proposed)))
    values = {**row, **context}
    return np.array([values[n] for n in feature_names], dtype=np.float64)


class MetaFilter:
    """Wraps a frozen :class:`~arven.ml.artifact.ModelArtifact`. Placement: called by the composition root
    (``arven.runs``/CLI) between ``DecisionEngine.decide()`` and ``RiskEngine.apply()`` - see
    ``docs/architecture.md`` section 13's "as implemented" note for Stage 6."""

    def __init__(self, artifact: ModelArtifact, model_id: str) -> None:
        self.artifact = artifact
        self.model_id = model_id
        self.n_seen = 0
        self.n_passed = 0
        self.n_vetoed = 0

    def describe(self) -> dict[str, Any]:
        return {"model_id": self.model_id, "model_family": self.artifact.model_family, "threshold": self.artifact.threshold}

    def apply(self, proposed: ProposedDecision, view: FeatureView) -> ProposedDecision:
        if proposed.action.value == "NO_TRADE":
            return proposed
        self.n_seen += 1
        x = build_row(view, proposed, self.artifact.feature_names).reshape(1, -1)
        p = float(self.artifact.predict_calibrated(x)[0])
        if p >= self.artifact.threshold:
            self.n_passed += 1
            return proposed
        self.n_vetoed += 1
        return dataclasses.replace(
            proposed,
            action=type(proposed.action)("NO_TRADE"),
            stop_pct=None, take_profit_pct=None, max_holding_minutes=None, contributing=(),
            reasons=proposed.reasons + (f"ml_filtered: p={p:.3f} < threshold={self.artifact.threshold:.3f} (model={self.model_id})",),
        )


class RandomFilter:
    """Control (decision D20/point 20): vetoes a fixed fraction of candidates chosen uniformly at random,
    using no model at all. Isolates "does trading less help" from "does the model's specific judgment
    help" - if a real model's backtest result is indistinguishable from this control at the same reject
    rate, the model's judgment is not (yet) adding anything a coin flip wouldn't."""

    def __init__(self, reject_rate: float, seed: int, model_id: str = "random_filter_control") -> None:
        if not (0.0 <= reject_rate <= 1.0):
            raise ValueError("reject_rate must be in [0, 1]")
        self.reject_rate = reject_rate
        self.rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed)))
        self.model_id = model_id
        self.n_seen = self.n_passed = self.n_vetoed = 0

    def describe(self) -> dict[str, Any]:
        return {"model_id": self.model_id, "model_family": "random_filter_control", "reject_rate": self.reject_rate}

    def apply(self, proposed: ProposedDecision, view: FeatureView) -> ProposedDecision:
        if proposed.action.value == "NO_TRADE":
            return proposed
        self.n_seen += 1
        if self.rng.random() >= self.reject_rate:
            self.n_passed += 1
            return proposed
        self.n_vetoed += 1
        return dataclasses.replace(
            proposed, action=type(proposed.action)("NO_TRADE"), stop_pct=None, take_profit_pct=None,
            max_holding_minutes=None, contributing=(),
            reasons=proposed.reasons + (f"random_filter_control: rejected (rate={self.reject_rate:.3f})",),
        )
