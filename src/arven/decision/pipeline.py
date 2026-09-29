"""The Stage 5 pipeline: regime detection + 3 strategies + decision engine + risk engine, wired into one
:class:`~arven.backtest.provider.SignalProvider` the Stage 4 backtester can run unmodified.

This is composition only (no new logic): each stage is built from its own config and called in the fixed
order the architecture specifies (regime -> strategies -> decision -> risk). Regime state and risk-engine
circuit-breaker state are reset in :meth:`prepare`, so two runs of the same window are independent and
reproducible; :meth:`decide` never does anything except call the four stages once, in order, on the current
decision time's causal ``FeatureView`` and ``PortfolioSnapshot`` — it holds no market data of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arven.backtest.provider import DecisionContext, PrepareInfo
from arven.core.backtest_config import BacktestConfig
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
    proposed: ProposedDecision
    risk: RiskDecision


class Stage5Pipeline:
    def __init__(self, regime_cfg: RegimeConfig, strategies_cfg: StrategiesConfig, risk_cfg: RiskConfig, bt_cfg: BacktestConfig) -> None:
        self.regime_cfg, self.strategies_cfg, self.risk_cfg = regime_cfg, strategies_cfg, risk_cfg
        self.strategies = build_strategies(strategies_cfg)
        gates = {s.strategy_id: s.gate for s in self.strategies}
        d = strategies_cfg.decision
        self.decision_engine = DecisionEngine(d.weights, gates, d.decision_threshold, d.conflict_threshold)
        self.risk_engine = RiskEngine(risk_cfg, bt_cfg)
        self.regime_detector = RegimeDetector(regime_cfg)
        self.history: list[DecisionRecord] = []

    def describe(self) -> dict[str, Any]:
        return {
            "name": PIPELINE_NAME,
            "strategy_ids": [s.strategy_id for s in self.strategies],
            "regime_config_hash": self.regime_cfg.config_hash(),
            "strategies_config_hash": self.strategies_cfg.config_hash(),
            "risk_config_hash": self.risk_cfg.config_hash(),
        }

    def prepare(self, info: PrepareInfo) -> None:
        self.regime_detector.reset()
        self.risk_engine.reset()
        self.history = []

    def decide(self, ctx: DecisionContext) -> Signal | None:
        regime = self.regime_detector.step(ctx.features, ctx.now_ms)
        candidates = tuple(c for c in (s.evaluate(ctx.features, ctx.now_ms) for s in self.strategies) if c is not None)
        proposed = self.decision_engine.decide(ctx.now_ms, list(candidates), regime)
        feat_ready = ctx.features.value("feat_ready", ctx.now_ms)
        fund_z = ctx.features.value("fund_z", ctx.now_ms)
        signal, risk_decision = self.risk_engine.apply(proposed, ctx.portfolio, ctx.now_ms, feat_ready, fund_z)
        self.history.append(DecisionRecord(ctx.now_ms, regime, candidates, proposed, risk_decision))
        return signal
