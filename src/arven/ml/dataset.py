"""Dataset construction: replay Stage 5's own (unmodified) regime/strategies/decision/risk code over a
window, resolve each eligible candidate's triple-barrier label, and assemble one numeric row per candidate.

Reuses Stage 5's real objects directly (``RegimeDetector``, the 3 strategies via
``arven.decision.pipeline.build_strategies``, ``DecisionEngine``, ``RiskEngine``) rather than
reimplementing any of their rules — the only "new" logic here is which candidates become dataset rows and
how they're encoded, matching the constraint to reuse existing mechanisms rather than build a parallel one.

**Eligibility (approved decision D3):** a candidate becomes a dataset row only if (a) Stage 5's regime and
strategies produced a non-``NO_TRADE`` decision, (b) it survives ``RiskEngine.apply()``'s *non-portfolio*
rules (data-quality, volatility guard, funding guard, sizing, liquidation-distance), and (c) its triple
barrier is resolvable within the stored 1m data. The four *portfolio-state* rules (position-already-open,
daily-loss halt, drawdown halt, cooldown) are bypassed by resetting the real ``RiskEngine`` and feeding it a
synthetic, permanently-flat ``PortfolioSnapshot`` before every single candidate — the real, unmodified rule
code still runs for every other check; only the portfolio-state precondition is neutralised. This labels
each candidate's own merit, independent of one particular backtest run's realized capital path.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from arven.backtest.clock import SimulationClock
from arven.backtest.marketdata import MarketData
from arven.backtest.provider import FeatureData, FeatureView, PortfolioSnapshot
from arven.core.backtest_config import BacktestConfig
from arven.core.config import CostsConfig
from arven.core.ml_config import MLConfig
from arven.core.regime_config import RegimeConfig
from arven.core.risk_config import RiskConfig
from arven.core.strategies_config import StrategiesConfig
from arven.core.types import Action
from arven.decision.engine import DecisionEngine, ProposedDecision
from arven.decision.pipeline import build_strategies
from arven.ml.labels import resolve_triple_barrier
from arven.regime.detector import RegimeDetector, TrendState, VolState
from arven.risk.engine import RiskEngine

TREND_LABELS: tuple[str, ...] = tuple(s.value for s in TrendState)
VOL_LABELS: tuple[str, ...] = tuple(s.value for s in VolState)
STRATEGY_IDS: tuple[str, ...] = ("trend_momentum", "breakout", "mean_reversion")

CONTEXT_COLUMNS: tuple[str, ...] = (
    tuple(f"regime_trend_{t}" for t in TREND_LABELS)
    + tuple(f"regime_vol_{v}" for v in VOL_LABELS)
    + ("regime_stress",)
    + tuple(f"contrib_{s}" for s in STRATEGY_IDS)
    + tuple(f"strength_{s}" for s in STRATEGY_IDS)
    + ("score", "confidence", "stop_pct", "take_profit_pct", "max_holding_minutes")
)

_FRESH_PORTFOLIO = PortfolioSnapshot(
    equity=1.0, wallet=1.0, side=0, qty=0.0, entry_price=0.0, unrealized=0.0, available_margin=1.0, order_pending=False
)


@dataclass(frozen=True, eq=False)
class Dataset:
    feature_names: tuple[str, ...]  # 60 causal Stage 3 columns (feat_ready excluded) + 18 context columns
    t_ms: np.ndarray
    horizon_ms: np.ndarray  # t_ms + max_holding_minutes*60000; used for purging
    action: np.ndarray  # +1 / -1
    label: np.ndarray  # 0/1
    net_return: np.ndarray
    x: np.ndarray  # (n_rows, n_features), float64
    n_candidates_total: int  # every non-NO_TRADE ProposedDecision observed
    n_ineligible_risk: int  # rejected by RiskEngine's non-portfolio rules
    n_ineligible_label: int  # risk-approved but the label horizon wasn't resolvable in the stored 1m data

    def __len__(self) -> int:
        return len(self.t_ms)


def build_context_vector(proposed: ProposedDecision) -> list[float]:
    """The canonical MetaFilter context encoding (fixes the Stage 6 pre-commit audit's train/serve skew
    finding): a pure function of ``proposed`` alone - the exact ``ProposedDecision`` object available at the
    MetaFilter position, both here (training) and in ``arven.ml.filter.build_row`` (live inference). Uses
    ``proposed.regime``/``proposed.stop_pct``/``proposed.take_profit_pct``/``proposed.max_holding_minutes`` -
    the *raw*, pre-``RiskEngine`` values - deliberately, never a risk-engine-processed ``Signal``: MetaFilter
    always runs strictly before ``RiskEngine`` (D2), so ``RiskEngine``'s stop/target bounding (rule 5) is not
    yet available at the point a live decision reaches the filter, and training must not use information the
    live path cannot see. (The *label* is still resolved against the real, risk-bounded ``Signal`` in
    :func:`build_dataset` below - that is correct and unrelated: the label asks "would this bounded trade
    have succeeded", the context features ask "what did MetaFilter see", and those are legitimately
    different values of the same underlying decision.)"""
    regime = proposed.regime
    contrib = {c.strategy_id: c.strength for c in proposed.all_candidates if c.strategy_id in proposed.contributing}
    vec = [1.0 if regime.trend.value == t else 0.0 for t in TREND_LABELS]
    vec += [1.0 if regime.vol.value == v else 0.0 for v in VOL_LABELS]
    vec.append(1.0 if regime.stress else 0.0)
    vec += [1.0 if s in proposed.contributing else 0.0 for s in STRATEGY_IDS]
    vec += [contrib.get(s, 0.0) for s in STRATEGY_IDS]
    vec += [
        proposed.score, proposed.confidence, proposed.stop_pct, proposed.take_profit_pct,
        float(proposed.max_holding_minutes) if proposed.max_holding_minutes is not None else 0.0,
    ]
    return vec


def build_dataset(
    market: MarketData,
    features: FeatureData,
    regime_cfg: RegimeConfig,
    strategies_cfg: StrategiesConfig,
    risk_cfg: RiskConfig,
    bt_cfg: BacktestConfig,
    costs_cfg: CostsConfig,
    ml_cfg: MLConfig,
) -> Dataset:
    clock = SimulationClock(features.t_ms)
    view = FeatureView(features.t_ms, features.names, features.values, clock, features.first_ready_ms)
    detector = RegimeDetector(regime_cfg)
    strategies = build_strategies(strategies_cfg)
    gates = {s.strategy_id: s.gate for s in strategies}
    d = strategies_cfg.decision
    decision_engine = DecisionEngine(d.weights, gates, d.decision_threshold, d.conflict_threshold)
    risk_engine = RiskEngine(risk_cfg, bt_cfg)

    stage3_names = tuple(n for n in features.names if n != "feat_ready")
    feature_names = stage3_names + CONTEXT_COLUMNS

    rows_t: list[int] = []
    rows_h: list[int] = []
    rows_action: list[int] = []
    rows_label: list[int] = []
    rows_ret: list[float] = []
    rows_x: list[list[float]] = []
    n_total = n_ineligible_risk = n_ineligible_label = 0

    while (t := clock.advance()) is not None:
        regime = detector.step(view, t)
        candidates = [c for c in (s.evaluate(view, t) for s in strategies) if c is not None]
        proposed = decision_engine.decide(t, candidates, regime)
        if proposed.action == Action.NO_TRADE:
            continue
        n_total += 1

        feat_ready = view.value("feat_ready", t)
        fund_z = view.value("fund_z", t)
        risk_engine.reset()  # neutralises the four portfolio-state rules (D3); every other rule runs for real
        signal, _risk_decision = risk_engine.apply(proposed, _FRESH_PORTFOLIO, t, feat_ready, fund_z)
        if signal is None:
            n_ineligible_risk += 1
            continue

        direction = 1 if signal.action == Action.LONG else -1
        fill_time_ms = t + bt_cfg.latency_ms
        label_result = resolve_triple_barrier(
            market, fill_time_ms, direction, signal.stop_pct, signal.take_profit_pct, signal.max_holding_minutes,
            costs_cfg, ml_cfg.labels.min_net_return_for_positive_label,
        )
        if label_result is None:
            n_ineligible_label += 1
            continue

        row = view.row(t)
        x_row = [row[n] for n in stage3_names] + build_context_vector(proposed)
        rows_t.append(t)
        rows_h.append(t + signal.max_holding_minutes * 60_000)
        rows_action.append(direction)
        rows_label.append(label_result.label)
        rows_ret.append(label_result.net_return)
        rows_x.append(x_row)

    x = np.array(rows_x, dtype=np.float64) if rows_x else np.empty((0, len(feature_names)))
    return Dataset(
        feature_names, np.array(rows_t, dtype=np.int64), np.array(rows_h, dtype=np.int64),
        np.array(rows_action, dtype=np.int64), np.array(rows_label, dtype=np.int64),
        np.array(rows_ret, dtype=np.float64), x, n_total, n_ineligible_risk, n_ineligible_label,
    )
