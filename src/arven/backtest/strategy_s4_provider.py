"""`SignalProvider` adapter for strategy S4 - "Impulse-Retest" (`docs/strategy_impulse_retest.md`;
detection math in `arven.engine.strategy_s4`). Lives in `arven.backtest`, not `arven.engine` - the same
`backtest -> engine` dependency direction Phase 3/4 already established, since this needs
`arven.backtest.provider`'s `SignalProvider`/`DecisionContext`/`PrepareInfo` and `arven.core.signal.Signal`.

**Ignores `ctx.features` entirely.** `EventBacktester` hands every registered provider the same legacy,
1h-gridded `FeatureView` regardless of the provider's own `trigger_tf` - useless for a 15m-triggered
strategy, which cannot even index into an hourly grid at a 15-minute mark. `decide()` instead looks up
this provider's own pre-built `setup_bars`/`trigger_bars` (`core.series.BarSeries`, truncated at
`ctx.now_ms` via `.available_until` - "truncate first, then compute", `strategy_s4.py`'s own idiom) and a
`MultiTFView` for the 4h context row - never the `FeatureView` it was given.

**One decision, two renderings** (spec section 10): `decide()` emits the legacy single-exit `Signal` (TP1
and the stop only) for the backtest/WFO/baselines/stress evaluation, driven through the unchanged Stage 4
execution model; `to_engine_signal()` builds the full multi-rung `EngineSignal` from the *same*
`ImpulseRetestDecision` for forward/paper use. Neither path recomputes the technical-analysis math
twice - `_compute_decision()` is the one source of truth both call.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from arven.backtest.provider import DecisionContext, PrepareInfo, SignalProvider
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
from arven.engine.strategy_s4 import (
    ImpulseRetestDecision,
    build_decision,
    confirmed_swings,
    confluence_zone,
    counter_trend_trendline,
    find_last_impulse,
    find_trigger,
    setup_tf_atr,
)

STRATEGY_ID = "s4_impulse_retest"
STRATEGY_VERSION = "v1"
RISK_FRACTION = 0.01  # fixed 1% of equity per signal, spec section 8 - never optimised
MIN_SETUP_BARS = 200  # enough 1h history to reliably find two confirmed swing pairs + their base candle


def make_spec() -> StrategySpec:
    return StrategySpec(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION, context_tfs=(Timeframe.H4,),
        setup_tf=Timeframe.H1, trigger_tf=Timeframe.M15, warmup_bars=MIN_SETUP_BARS,
    )


class ImpulseRetestProvider:
    """Constructed once per run with the *entire* window's own bar history (never a live DB connection) -
    `decide()` truncates internally at `ctx.now_ms`, exactly like every other causal component in this
    project."""

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
        self._last_decision: ImpulseRetestDecision | None = None  # the most recent decide() output, for to_engine_signal()
        self.placed = 0
        # Cache of the setup_tf-side computation (everything that depends only on setup_bars, not on the
        # trigger_tf tick that is currently running), keyed by the truncated setup array's own length. A
        # new setup_tf (1h) bar becomes available only once an hour, but decide() is called every
        # trigger_tf (15m) tick - four calls out of five would otherwise recompute an unchanged result from
        # scratch over an ever-growing array (ATR/swings are each O(n) per call), making a multi-year
        # backtest effectively O(n^2) in wall-clock time. Found and fixed before the first real
        # development-period run completed - see `docs/current_state.md`'s "Phase 7b" section.
        self._setup_cache_len: int | None = None
        self._setup_cache: tuple[BarSeries, float, object | None, object | None] | None = None

    def _line_time(self, open_ms: np.ndarray) -> np.ndarray:
        """The time axis the trend line is drawn on: real epoch ms around the clock; *trading time* for a session
        market (gold), so a line continues across a weekend as it does on a chart without weekend bars."""
        cal = self._setup_bars.calendar
        return open_ms if cal is None or cal.always_open else np.asarray(cal.trading_ms(open_ms), dtype=np.int64)

    def describe(self) -> dict[str, Any]:
        return {"name": STRATEGY_ID, "version": STRATEGY_VERSION, "risk_fraction": RISK_FRACTION}

    def prepare(self, info: PrepareInfo) -> None:
        return None

    def _setup_side(self, now_ms: int) -> tuple[BarSeries, float, object, object, object] | None:
        """Everything derived from `setup_bars` alone (ATR, swings, the active impulse, zone, trendline) -
        cached across ticks that fall within the same, still-current setup_tf bar. Returns
        ``(setup, atr_at_as_of, impulse, zone, trendline)`` or ``None`` if no impulse/zone/trendline
        exists yet (the 4h-slope-agreement filter is applied separately, by the caller)."""
        setup = self._setup_bars.regularized_until(now_ms)
        if len(setup) < MIN_SETUP_BARS:
            return None
        if self._setup_cache_len == len(setup):
            setup_cached, atr_at_as_of, impulse, zone_and_line = self._setup_cache  # type: ignore[misc]
        else:
            atr_setup = setup_tf_atr(setup.high, setup.low, setup.close)
            swings = confirmed_swings(setup.high, setup.low)
            as_of = len(setup) - 1
            impulse = find_last_impulse(swings, atr_setup, as_of)
            zone_and_line = None
            if impulse is not None:
                zone = confluence_zone(impulse, setup.high, setup.low, atr_setup)
                if zone is not None:
                    trendline = counter_trend_trendline(swings, impulse, as_of, self._line_time(setup.open_time_ms))
                    if trendline is not None:
                        zone_and_line = (zone, trendline)
            atr_at_as_of = float(atr_setup[as_of])
            self._setup_cache_len = len(setup)
            self._setup_cache = (setup, atr_at_as_of, impulse, zone_and_line)
            setup_cached = setup

        if impulse is None or zone_and_line is None:
            return None
        zone, trendline = zone_and_line
        return setup_cached, atr_at_as_of, impulse, zone, trendline

    def _compute_decision(self, now_ms: int) -> ImpulseRetestDecision | None:
        trigger = self._trigger_bars.regularized_until(now_ms)
        if len(trigger) < 2:
            return None

        try:
            h4_row = self._multitf.row_at(Timeframe.H4, now_ms)
        except LookAheadError:
            return None
        slope = h4_row["ema_slope_50"]
        if not math.isfinite(slope):
            return None

        side_result = self._setup_side(now_ms)
        if side_result is None:
            return None
        setup, atr_at_entry, impulse, zone, trendline = side_result
        if (impulse.side == 1 and slope <= 0) or (impulse.side == -1 and slope >= 0):
            return None  # spec section 1.1: direction must agree with the 4h trend

        search_from = int(np.searchsorted(trigger.open_time_ms, setup.open_time_ms[impulse.end.index]))
        trigger_idx = find_trigger(
            trigger.close, trigger.high, trigger.low, self._line_time(trigger.open_time_ms), trendline, zone, impulse.side, search_from,
        )
        if trigger_idx is None or trigger_idx != len(trigger) - 1:
            return None  # only a *fresh* trigger on the current decision bar fires - never a stale one

        entry_price = float(trigger.close[trigger_idx])
        if not math.isfinite(atr_at_entry) or atr_at_entry <= 0:
            return None
        return build_decision(impulse, zone, entry_price, atr_at_entry, trigger_idx)

    def decide(self, ctx: DecisionContext) -> Signal | None:
        if ctx.portfolio.side != 0 or ctx.portfolio.order_pending:
            self._last_decision = None
            return None  # never propose a second entry while one is open or pending
        decision = self._compute_decision(ctx.now_ms)
        self._last_decision = decision
        if decision is None:
            return None
        self.placed += 1
        tp1 = decision.targets[0]
        stop_pct = abs(decision.entry - decision.stop) / decision.entry
        take_profit_pct = abs(tp1.price - decision.entry) / decision.entry
        return Signal(
            t_ms=ctx.now_ms,
            action=Action.LONG if decision.side == 1 else Action.SHORT,
            notional_fraction=RISK_FRACTION / stop_pct,
            stop_pct=stop_pct,
            take_profit_pct=take_profit_pct,
            tag=f"{STRATEGY_ID}|conf={decision.confidence:.2f}",
        )

    def to_engine_signal(self, event_time_ms: int, *, feature_version: str, config_hash: str, git_commit: str | None) -> EngineSignal | None:
        """The full multi-rung ladder for the *same* decision `decide()` most recently produced (forward/
        paper use only - never called by the backtest/WFO/baselines/stress evaluation, spec section 10)."""
        decision = self._last_decision
        if decision is None:
            return None
        ladder = tuple(
            TPLevel(t.r_multiple, t.close_fraction, t.price) for t in decision.targets
        )
        reasons = (
            f"impulse {('bullish' if decision.side == 1 else 'bearish')} size={decision.impulse.size:.2f}",
            f"zone=[{decision.zone.lower:.2f},{decision.zone.upper:.2f}] overlap={decision.zone.overlap_fraction:.0%}",
            "4h ema_slope_50 agrees with impulse direction",
        )
        return EngineSignal(
            symbol=self.symbol, side=decision.side, strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
            grade=Grade.EXPERIMENTAL, event_time_ms=event_time_ms, entry_reference=decision.entry,
            stop=decision.stop, tp_ladder=ladder, risk_fraction=RISK_FRACTION, confidence=decision.confidence,
            regime=f"S4_IMPULSE_{'UP' if decision.side == 1 else 'DOWN'}", reasons=reasons, risk_checks=(),
            versions=SignalVersions(feature_version, config_hash, git_commit),
        )
