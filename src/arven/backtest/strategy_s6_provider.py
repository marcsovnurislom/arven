"""`SignalProvider` adapter for strategy S6 - "Trend-Pullback" (`docs/strategy_trend_pullback.md`; math in
`arven.engine.strategy_s6`). Same shape and dependency direction as the S4/S5 adapters (``backtest -> engine``).
One cached decision, rendered twice: the legacy single-exit ``Signal`` (TP1 + stop) and the full-ladder
``EngineSignal``. The only state beyond caches is the cooldown timestamp (spec section 4); it is a pure function
of the sequence of decisions, so a full replay from the start always reproduces it."""

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
from arven.engine.strategy_s6 import (
    COOLDOWN_HOURS,
    MIN_SETUP_BARS,
    PullbackState,
    TrendPullbackDecision,
    bounce_fires,
    build_decision,
    pullback_ok,
    pullback_state,
)

STRATEGY_ID = "s6_trend_pullback"
STRATEGY_VERSION = "v1"
RISK_FRACTION = 0.01
HOUR_MS = 3_600_000


def make_spec() -> StrategySpec:
    return StrategySpec(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION, context_tfs=(Timeframe.H4,),
        setup_tf=Timeframe.H1, trigger_tf=Timeframe.M15, warmup_bars=MIN_SETUP_BARS,
    )


class TrendPullbackProvider:
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
        self._last_decision: TrendPullbackDecision | None = None
        self._last_signal_ms: int | None = None
        self.placed = 0
        self._cache_len: int | None = None
        self._cache_state: PullbackState | None = None

    def _elapsed_ms(self, since_ms: int, now_ms: int) -> int:
        """Cooldown clock: wall time around the clock; trading time on a session market (a weekend does not use it up)."""
        cal = self._setup_bars.calendar
        if cal is None or cal.always_open:
            return now_ms - since_ms
        return int(cal.trading_ms(now_ms)) - int(cal.trading_ms(since_ms))

    def describe(self) -> dict[str, Any]:
        return {"name": STRATEGY_ID, "version": STRATEGY_VERSION, "risk_fraction": RISK_FRACTION}

    def prepare(self, info: PrepareInfo) -> None:
        return None

    def _state(self, now_ms: int) -> PullbackState | None:
        setup = self._setup_bars.regularized_until(now_ms)
        if len(setup) < MIN_SETUP_BARS:
            return None
        if self._cache_len != len(setup):
            self._cache_state = pullback_state(setup.high, setup.low, setup.close)
            self._cache_len = len(setup)
        return self._cache_state

    def _compute_decision(self, now_ms: int) -> TrendPullbackDecision | None:
        if self._last_signal_ms is not None and self._elapsed_ms(self._last_signal_ms, now_ms) < COOLDOWN_HOURS * HOUR_MS:
            return None
        trigger = self._trigger_bars.regularized_until(now_ms)
        try:
            slope = self._multitf.row_at(Timeframe.H4, now_ms)["ema_slope_50"]
        except LookAheadError:
            return None
        if not math.isfinite(slope) or slope == 0:
            return None
        side = 1 if slope > 0 else -1
        state = self._state(now_ms)
        if state is None or not pullback_ok(side, state):
            return None
        if not bounce_fires(side, trigger.high, trigger.low, trigger.close):
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
        self._last_signal_ms = ctx.now_ms
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
            f"pullback to 1h EMA20 ({d.state.ema:.2f}) held, bounce on 15m",
            "4h ema_slope_50 agrees with the trade direction",
        )
        return EngineSignal(
            symbol=self.symbol, side=d.side, strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
            grade=Grade.EXPERIMENTAL, event_time_ms=event_time_ms, entry_reference=d.entry, stop=d.stop,
            tp_ladder=ladder, risk_fraction=RISK_FRACTION, confidence=d.confidence,
            regime=f"S6_PULLBACK_{'UP' if d.side == 1 else 'DOWN'}", reasons=reasons, risk_checks=(),
            versions=SignalVersions(feature_version, config_hash, git_commit),
        )
