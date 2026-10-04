"""The Stage 5 pipeline: regime detection + 3 strategies + decision engine + risk engine, wired into one
:class:`~arven.backtest.provider.SignalProvider` the Stage 4 backtester can run unmodified.

This is composition only (no new logic): each stage is built from its own config and called in the fixed
order the architecture specifies (regime -> strategies -> decision -> risk). Regime state and risk-engine
circuit-breaker state are reset in :meth:`prepare`, so two runs of the same window are independent and
reproducible; :meth:`decide` never does anything except call the four stages once, in order, on the current
decision time's causal ``FeatureView`` and ``PortfolioSnapshot`` — it holds no market data of its own.

**Stage 6 (optional, additive):** the constructor takes an optional ``ml_filter``. When ``None`` (the
default), behavior is byte-identical to the committed Stage 5 pipeline — the exact same four calls in the
exact same order, nothing added, nothing skipped (verified by
``tests/pipeline/test_stage5_no_ml_regression.py``). When given, it is called with the *unmodified*
``ProposedDecision`` right after ``DecisionEngine.decide()`` and strictly before ``RiskEngine.apply()`` —
see ``docs/architecture.md`` section 13's Stage 6 note for why this ordering, not the diagram's. It may only
return the same decision or a downgraded ``NO_TRADE`` (``arven.ml.filter.MetaFilter`` enforces this); this
module never imports ``arven.ml`` (a ``Protocol`` describes the expected shape instead), so Stage 5 carries
no dependency on Stage 6 or its `lightgbm` dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from arven.backtest.provider import DecisionContext, FeatureView, PrepareInfo
from arven.core.backtest_config import BacktestConfig
from arven.core.macro_config import MacroEvent
from arven.core.regime_config import RegimeConfig
from arven.core.risk_config import RiskConfig
from arven.core.signal import Signal
from arven.core.strategies_config import StrategiesConfig
from arven.decision.engine import DecisionEngine, ProposedDecision
from arven.regime.detector import Regime, RegimeDetector
from arven.risk.engine import RiskDecision, RiskEngine
from arven.strategies.base import CandidateSignal, Strategy
from arven.strategies.breakout import BreakoutStrategy
from arven.strategies.mean_reversion import MeanReversionStrategy
from arven.strategies.trend_momentum import TrendMomentumStrategy

PIPELINE_NAME = "stage5_pipeline"


class MLFilterProtocol(Protocol):
    def apply(self, proposed: ProposedDecision, view: FeatureView) -> ProposedDecision: ...


def build_strategies(cfg: StrategiesConfig) -> tuple[Strategy, ...]:
    return (
        TrendMomentumStrategy(cfg.trend_momentum),
        BreakoutStrategy(cfg.breakout),
        MeanReversionStrategy(cfg.mean_reversion),
    )


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One decision time's full trace: every candidate, the regime, the proposal and the risk outcome —
    the point-in-time explanation payload (docs/architecture.md section 4's ``Signal(... explained)``)."""

    t_ms: int
    regime: Regime
    candidates: tuple[CandidateSignal, ...]
    proposed: ProposedDecision  # the decision engine's own output, BEFORE any Stage 6 filtering
    risk: RiskDecision
    ml_filtered: bool = False  # True if a Stage 6 MetaFilter downgraded `proposed` to NO_TRADE before risk


class Stage5Pipeline:
    def __init__(
        self, regime_cfg: RegimeConfig, strategies_cfg: StrategiesConfig, risk_cfg: RiskConfig, bt_cfg: BacktestConfig,
        ml_filter: MLFilterProtocol | None = None, macro_events: tuple[MacroEvent, ...] = (),
    ) -> None:
        self.regime_cfg, self.strategies_cfg, self.risk_cfg = regime_cfg, strategies_cfg, risk_cfg
        self.strategies = build_strategies(strategies_cfg)
        gates = {s.strategy_id: s.gate for s in self.strategies}
        d = strategies_cfg.decision
        self.decision_engine = DecisionEngine(d.weights, gates, d.decision_threshold, d.conflict_threshold)
        self.risk_engine = RiskEngine(risk_cfg, bt_cfg, macro_events)
        self.regime_detector = RegimeDetector(regime_cfg)
        self.ml_filter = ml_filter
        self.history: list[DecisionRecord] = []

    def describe(self) -> dict[str, Any]:
        from arven.core.macro_config import macro_events_hash

        d = {
            "name": PIPELINE_NAME,
            "strategy_ids": [s.strategy_id for s in self.strategies],
            "regime_config_hash": self.regime_cfg.config_hash(),
            "strategies_config_hash": self.strategies_cfg.config_hash(),
            "risk_config_hash": self.risk_cfg.config_hash(),
            "macro_events_hash": macro_events_hash(self.risk_engine.macro_events),
            "macro_events_count": len(self.risk_engine.macro_events),
        }
        if self.ml_filter is not None and hasattr(self.ml_filter, "describe"):
            d["ml_filter"] = self.ml_filter.describe()
        return d

    def prepare(self, info: PrepareInfo) -> None:
        self.regime_detector.reset()
        self.risk_engine.reset()
        self.history = []

    def decide(self, ctx: DecisionContext) -> Signal | None:
        regime = self.regime_detector.step(ctx.features, ctx.now_ms)
        candidates = tuple(c for c in (s.evaluate(ctx.features, ctx.now_ms) for s in self.strategies) if c is not None)
        proposed = self.decision_engine.decide(ctx.now_ms, list(candidates), regime)
        risk_input = proposed
        ml_filtered = False
        if self.ml_filter is not None and proposed.action.value != "NO_TRADE":
            risk_input = self.ml_filter.apply(proposed, ctx.features)
            ml_filtered = risk_input.action.value == "NO_TRADE"
        feat_ready = ctx.features.value("feat_ready", ctx.now_ms)
        fund_z = ctx.features.value("fund_z", ctx.now_ms)
        signal, risk_decision = self.risk_engine.apply(risk_input, ctx.portfolio, ctx.now_ms, feat_ready, fund_z)
        self.history.append(DecisionRecord(ctx.now_ms, regime, candidates, proposed, risk_decision, ml_filtered))
        return signal
