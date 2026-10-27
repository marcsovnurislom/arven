"""`SignalProvider` adapter for strategy S5 - "Squeeze-Breakout" (`docs/strategy_range_breakout.md`; math in
`arven.engine.strategy_s5`). Same shape and dependency direction as the S4 adapter: lives in `arven.backtest`
(imports from `arven.engine`, never the reverse), ignores ``ctx.features``, truncates its own bar series at
``ctx.now_ms``, and renders one cached decision twice - the legacy single-exit ``Signal`` (TP1 + stop) for the
backtest, the full ladder ``EngineSignal`` for paper/live."""

from __future__ import annotations

import math
from typing import Any

from arven.backtest.provider import DecisionContext, PrepareInfo
from arven.core.series import BarSeries
from arven.core.signal import Signal
from arven.core.timeframes import Timeframe
from arven.core.types import Action
from arven.engine.errors import LookAheadError
from arven.engine.features import TFFeatureParams
from arven.engine.grading import Grade
from arven.engine.multitf import MultiTFView
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.spec import StrategySpec
from arven.engine.strategy_s5 import (
    MIN_SETUP_BARS,
    RangeBreakoutDecision,
    RangeState,
    breakout_side,
    build_decision,
    squeeze_range,
)

STRATEGY_ID = "s5_squeeze_breakout"
STRATEGY_VERSION = "v1"
RISK_FRACTION = 0.01


def make_spec() -> StrategySpec:
    return StrategySpec(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION, context_tfs=(Timeframe.H4,),
        setup_tf=Timeframe.H1, trigger_tf=Timeframe.M15, warmup_bars=MIN_SETUP_BARS,
    )


class SqueezeBreakoutProvider:
    def __init__(
        self, setup_bars: BarSeries, trigger_bars: BarSeries, context_bars: BarSeries,
        *, tf_params: TFFeatureParams | None = None, symbol: str = "BTCUSDT",
    ) -> None:
        if setup_bars.timeframe != Timeframe.H1 or trigger_bars.timeframe != Timeframe.M15 or context_bars.timeframe != Timeframe.H4:
            raise ValueError("setup_bars must be 1h, trigger_bars 15m, context_bars 4h")
        self.symbol = symbol  # stamped on the EngineSignal; the decision never depends on it
        self._setup_bars = setup_bars
        self._trigger_bars = trigger_bars
        self._multitf = MultiTFView.from_bars({Timeframe.H4: context_bars}, (Timeframe.H4,), tf_params or TFFeatureParams())
        self._last_decision: RangeBreakoutDecision | None = None
        self.placed = 0
        # the squeeze range changes only when a new 1h bar closes - cache it by the truncated length
        self._cache_len: int | None = None
        self._cache_state: RangeState | None = None

    def describe(self) -> dict[str, Any]:
        return {"name": STRATEGY_ID, "version": STRATEGY_VERSION, "risk_fraction": RISK_FRACTION}

    def prepare(self, info: PrepareInfo) -> None:
        return None

    def _range_state(self, now_ms: int) -> RangeState | None:
        setup = self._setup_bars.regularized_until(now_ms)
        if len(setup) < MIN_SETUP_BARS:
            return None
        if self._cache_len != len(setup):
            self._cache_state = squeeze_range(setup.high, setup.low, setup.close)
            self._cache_len = len(setup)
        return self._cache_state

    def _compute_decision(self, now_ms: int) -> RangeBreakoutDecision | None:
        trigger = self._trigger_bars.regularized_until(now_ms)
        if len(trigger) < 2:
            return None
        try:
            slope = self._multitf.row_at(Timeframe.H4, now_ms)["ema_slope_50"]
        except LookAheadError:
            return None
        if not math.isfinite(slope):
            return None
        state = self._range_state(now_ms)
        if state is None:
            return None
        side = breakout_side(float(trigger.close[-1]), float(trigger.close[-2]), state, slope)
        if side == 0:
            return None
        return build_decision(side, float(trigger.close[-1]), state)

    def decide(self, ctx: DecisionContext) -> Signal | None:
        if ctx.portfolio.side != 0 or ctx.portfolio.order_pending:
            self._last_decision = None
            return None
        decision = self._compute_decision(ctx.now_ms)
        self._last_decision = decision
        if decision is None:
            return None
        self.placed += 1
        tp1 = decision.targets[0]
        stop_pct = abs(decision.entry - decision.stop) / decision.entry
        return Signal(
            t_ms=ctx.now_ms, action=Action.LONG if decision.side == 1 else Action.SHORT,
            notional_fraction=RISK_FRACTION / stop_pct, stop_pct=stop_pct,
            take_profit_pct=abs(tp1.price - decision.entry) / decision.entry,
            tag=f"{STRATEGY_ID}|conf={decision.confidence:.2f}",
        )

    def to_engine_signal(self, event_time_ms: int, *, feature_version: str, config_hash: str, git_commit: str | None) -> EngineSignal | None:
        d = self._last_decision
        if d is None:
            return None
        ladder = tuple(TPLevel(t.r_multiple, t.close_fraction, t.price) for t in d.targets)
        reasons = (
            f"squeeze range [{d.state.lo:.2f},{d.state.hi:.2f}] width={d.state.width / d.state.atr:.1f} ATR",
            "4h ema_slope_50 agrees with breakout direction",
        )
        return EngineSignal(
            symbol=self.symbol, side=d.side, strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
            grade=Grade.EXPERIMENTAL, event_time_ms=event_time_ms, entry_reference=d.entry, stop=d.stop,
            tp_ladder=ladder, risk_fraction=RISK_FRACTION, confidence=d.confidence,
            regime=f"S5_BREAKOUT_{'UP' if d.side == 1 else 'DOWN'}", reasons=reasons, risk_checks=(),
            versions=SignalVersions(feature_version, config_hash, git_commit),
        )
