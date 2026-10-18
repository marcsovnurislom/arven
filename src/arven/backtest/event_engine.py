"""Event-driven backtest loop (signal-product build-out, `docs/ARVEN_MASTER_PROMPT.md` Phase 3).

The generalisation of :class:`arven.backtest.engine.Backtester` (kept, unmodified, for the legacy path and
the CLI) from a flat 1h decision grid to an :class:`arven.engine.clock.EventClock` that emits
:class:`arven.engine.events.BarCloseEvent` s for one or more timeframes. The Stage 4 execution layer
(:class:`~arven.backtest.execution.Simulator`: fills, fees, slippage, funding, margin, liquidations, exits)
is reused **unchanged** - this module only decides *when* to call it, with exactly the same call sequence
``Backtester.run`` makes for every dispatched event:

1. ``j = first 1m bar at or after t``; ``sim.run_window(cursor, j)``; ``cursor = j``;
2. ``sim.add_point(t, close of bar j-1, DECISION)``;
3. the provider registered for ``event.timeframe`` gets a :class:`DecisionContext` (causal ``FeatureView``
   bound to ``t``, portfolio snapshot) and its signal becomes an order (or a rejection) exactly as in
   ``Backtester.run``.

``t`` is the event's ``close_ms`` (the bar close, the same decision-time convention as the legacy grid);
availability delay is handled the same way as the legacy engine, through ``cfg.latency_ms >=
data.bar_availability_delay_seconds`` (checked in the constructor).

Events whose timeframe has no registered provider are skipped entirely (no simulation call at all; the
next dispatched event's ``run_window`` covers those 1m bars), so adding unused timeframes to the clock
cannot change a result. Same-instant events are dispatched in the clock's own order (Phase 1 tie rule:
coarsest timeframe first). One account, one net position: a second provider's entry while an order is
pending or a position is open is rejected (``position_open``), exactly as a repeated entry is in the
legacy engine - no pyramiding.

Proof of equivalence: with a single provider on ``Timeframe.H1`` and a clock emitting the 1h closes of the
window, the result is byte-identical (same ``report.result_hash``) to ``Backtester.run`` - see
``tests/engine/test_event_backtest_equivalence.py``.

Module boundary (``tests/backtest/test_event_engine_static_rules.py``): this file imports from
``arven.engine`` only the clock/event vocabulary, from ``arven.backtest.engine`` only the
``BacktestResult`` dataclass (never ``Backtester`` itself), and never ``arven.backtest.clock``. The
dependency points one way - ``arven.backtest`` -> ``arven.engine`` - so ``arven.engine`` stays free of any
``arven.backtest`` import and no legacy ``arven.backtest`` module imports this one.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from arven.backtest.costs import require_taker_only
from arven.backtest.engine import BacktestResult
from arven.backtest.errors import ConfigurationError, DataError, SignalError
from arven.backtest.execution import Simulator
from arven.backtest.marketdata import MarketData
from arven.backtest.provider import DecisionContext, FeatureData, FeatureView, PortfolioSnapshot, PrepareInfo, SignalProvider
from arven.backtest.types import EquityKind, Order, OrderKind, Side
from arven.core.backtest_config import BacktestConfig
from arven.core.config import AppConfig
from arven.core.sessions import SessionCalendar, session_decision_mask
from arven.core.splitguard import AllowedWindow
from arven.core.timeframes import Timeframe
from arven.core.types import Action
from arven.engine.clock import EventClock, SimulatedEventClock
from arven.engine.events import BarCloseEvent


def timeframe_grid(start_ms: int, end_ms: int, tf: Timeframe, calendar: SessionCalendar | None = None) -> np.ndarray:
    """Epoch-aligned ``tf`` bar closes (= decision times) in ``[start_ms, end_ms)``; for a session market only those
    :func:`arven.core.sessions.session_decision_mask` allows.

    For ``Timeframe.H1`` and an hour-aligned window this is exactly the legacy ``engine.decision_grid``."""
    first = -(-start_ms // tf.ms) * tf.ms
    grid = np.arange(first, end_ms, tf.ms, dtype=np.int64)
    return grid if calendar is None or calendar.always_open else grid[session_decision_mask(calendar, grid, tf)]


class WindowEventClock:
    """An :class:`EventClock` emitting, for every timeframe, exactly the bar closes in ``[start_ms, end_ms)``
    - the event-driven counterpart of the legacy window grid (whose first decision is the close at
    ``start_ms`` of the bar that opened before the window).

    Built from :class:`SimulatedEventClock` (so the Phase 1 ordering and tie rule apply unchanged), started
    one coarsest bar earlier and filtered to the window."""

    def __init__(
        self, symbol: str, timeframes: tuple[Timeframe, ...], start_ms: int, end_ms: int, delay_ms: int = 0,
        calendar: SessionCalendar | None = None,
    ) -> None:
        if not timeframes:
            raise ValueError("at least one timeframe is required")
        if end_ms <= start_ms:
            raise ValueError("end_ms must be after start_ms")
        coarsest = max(tf.ms for tf in timeframes)
        inner = SimulatedEventClock(symbol, timeframes, start_ms - coarsest, end_ms, delay_ms)
        events = [e for e in inner.events if start_ms <= e.close_ms < end_ms]
        if calendar is not None and not calendar.always_open:  # a session market: only actionable closes
            events = [e for e in events if bool(session_decision_mask(calendar, np.array([e.close_ms]), e.timeframe)[0])]
        self._events: tuple[BarCloseEvent, ...] = tuple(events)
        self._i = -1

    @property
    def events(self) -> tuple[BarCloseEvent, ...]:
        return self._events

    @property
    def now_ms(self) -> int:
        if self._i < 0:
            raise RuntimeError("clock has not started")
        return self._events[self._i].close_ms

    @property
    def started(self) -> bool:
        return self._i >= 0

    def advance(self) -> BarCloseEvent | None:
        if self._i + 1 >= len(self._events):
            return None
        self._i += 1
        return self._events[self._i]


class _DecisionTime:
    """What ``FeatureView`` reads as "now": the close time of the event being dispatched (only ``now_ms``
    is used by the view; nothing here can advance time)."""

    def __init__(self) -> None:
        self._t: int | None = None

    @property
    def now_ms(self) -> int:
        if self._t is None:
            raise RuntimeError("no event has been dispatched yet")
        return self._t

    def set(self, t_ms: int) -> None:
        self._t = t_ms

    def advance(self) -> int | None:  # pragma: no cover - part of the legacy Clock protocol, never called
        raise RuntimeError("the event loop owns time; FeatureView never advances it")


class EventBacktester:
    """Same constructor contract and validation as :class:`arven.backtest.engine.Backtester`; ``run`` takes
    an event clock and the providers keyed by the timeframe they trigger on."""

    def __init__(
        self,
        app: AppConfig,
        cfg: BacktestConfig,
        window: AllowedWindow,
        market: MarketData,
        features: FeatureData,
        *,
        stress: bool = False,
    ) -> None:
        require_taker_only(app.costs)
        if cfg.latency_ms < app.data.bar_availability_delay_seconds * 1000:
            raise ConfigurationError("latency_minutes must be >= data.bar_availability_delay_seconds")
        if market.window_start_ms != window.start_ms or market.window_end_ms != window.end_ms:
            raise DataError("market data window does not match the allowed window")
        self._calendar = app.session_calendar()
        hourly = timeframe_grid(window.start_ms, window.end_ms, Timeframe.H1, self._calendar)
        if len(features.t_ms) != len(hourly) or (len(hourly) and np.any(features.t_ms != hourly)):
            raise DataError("feature rows do not match the hourly grid of the window")
        self.app, self.cfg, self.window, self.market, self.features, self.stress = app, cfg, window, market, features, stress

    def grid(self, tf: Timeframe) -> np.ndarray:
        """The decision times a provider on ``tf`` will be called at (what its ``PrepareInfo`` carries)."""
        return timeframe_grid(self.window.start_ms, self.window.end_ms, tf, self._calendar)

    def run(self, clock: EventClock, providers: Mapping[Timeframe, SignalProvider]) -> BacktestResult:
        if not providers:
            raise ConfigurationError("at least one provider is required")
        if len({id(p) for p in providers.values()}) != len(providers):
            raise ConfigurationError("one provider object may be registered under only one timeframe")
        md, cfg, win = self.market, self.cfg, self.window
        order_tfs = sorted(providers, key=lambda tf: -tf.ms)  # deterministic, coarsest first (Phase 1 tie rule)
        grids = {tf: self.grid(tf) for tf in order_tfs}
        now = _DecisionTime()
        view = FeatureView(self.features.t_ms, self.features.names, self.features.values, now, self.features.first_ready_ms)  # type: ignore[arg-type]
        for tf in order_tfs:
            providers[tf].prepare(PrepareInfo(grids[tf].copy(), win.end_ms, self.features.first_ready_ms))
        sim = Simulator(md, cfg, self.app.costs, stress=self.stress)
        counts = {"none": 0, "no_trade": 0, "entry": 0, "close": 0, "close_ignored": 0}
        next_order_id = 1
        cursor = 0
        n_decisions = 0
        seen = dict.fromkeys(order_tfs, 0)
        last_close: int | None = None

        while (event := clock.advance()) is not None:
            t = event.close_ms
            if last_close is not None and t < last_close:
                raise DataError(f"event clock went backwards: {t} after {last_close}")
            last_close = t
            if not win.contains_ms(t):
                raise DataError(f"event at {t} lies outside the window [{win.start_ms}, {win.end_ms})")
            provider = providers.get(event.timeframe)
            if provider is None:
                continue
            k = seen[event.timeframe]
            grid = grids[event.timeframe]
            if k >= len(grid) or int(grid[k]) != t:
                raise DataError(f"{event.timeframe} event at {t} does not match the expected decision time")
            seen[event.timeframe] = k + 1

            j = md.first_at_or_after(t)
            sim.run_window(cursor, j)
            cursor = j
            price = float(md.close[j - 1]) if j > 0 else None
            point = sim.add_point(t, price, EquityKind.DECISION)
            n_decisions += 1
            now.set(t)
            pos = sim.state.position
            snap = PortfolioSnapshot(
                equity=point.equity,
                wallet=point.wallet,
                side=0 if pos is None else int(pos.side),
                qty=0.0 if pos is None else pos.qty,
                entry_price=0.0 if pos is None else pos.entry_price,
                unrealized=point.unrealized,
                available_margin=point.wallet - point.margin,
                order_pending=sim.pending_entry is not None or sim.pending_close is not None,
            )
            signal = provider.decide(DecisionContext(t, k, view, snap, win.period.value))
            if signal is None:
                counts["none"] += 1
                continue
            if signal.t_ms != t:
                raise SignalError(f"signal time {signal.t_ms} does not match the decision time {t}")
            eligible = t + cfg.latency_ms
            if signal.action == Action.NO_TRADE:
                if not signal.close_position:
                    counts["no_trade"] += 1
                elif pos is None or sim.pending_close is not None:
                    counts["close_ignored"] += 1
                else:
                    order = Order(next_order_id, OrderKind.CLOSE, pos.side, t, eligible, point.equity, None, None, None, None, signal.tag)
                    next_order_id += 1
                    counts["close"] += 1
                    sim.submit(order)
                continue
            side = Side.LONG if signal.action == Action.LONG else Side.SHORT
            order = Order(
                next_order_id, OrderKind.ENTRY, side, t, eligible, point.equity, signal.notional_fraction,
                signal.stop_pct, signal.take_profit_pct, signal.max_holding_minutes, signal.tag,
            )
            next_order_id += 1
            counts["entry"] += 1
            if pos is not None or sim.pending_entry is not None:
                sim.reject(order, "position_open", f"side={int(pos.side) if pos else 0}")
            elif signal.notional_fraction > cfg.leverage:  # type: ignore[operator]
                sim.reject(order, "exceeds_leverage_cap", f"fraction={signal.notional_fraction:.8f};leverage={cfg.leverage:.8f}")
            else:
                sim.submit(order)

        missing = [str(tf) for tf in order_tfs if seen[tf] != len(grids[tf])]
        if missing:
            raise DataError(f"event clock did not emit every decision time of the window for: {', '.join(missing)}")
        sim.run_window(cursor, len(md))
        sim.finish()
        return BacktestResult(
            period=win.period.value,
            window_start_ms=win.start_ms,
            window_end_ms=win.end_ms,
            initial_equity=cfg.initial_equity_usdt,
            final_wallet=sim.state.wallet,
            orders=tuple(sim.order_events),
            fills=tuple(sim.fills),
            funding=tuple(sim.funding_events),
            trades=tuple(sim.trades),
            equity=tuple(sim.equity),
            low_points=tuple(sim.low_points),
            signal_counts=counts,
            n_decisions=n_decisions,
            stress=self.stress,
        )
