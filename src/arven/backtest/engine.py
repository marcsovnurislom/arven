"""The backtest driver: clock loop, decision context, signal -> order handling.

Per decision time ``t`` (a 1h bar close, from the Stage 3 grid):

1. simulate the 1m bars since the previous decision (fills, funding, exits, liquidations);
2. mark the account at the close of the last 1m bar before ``t`` and record a DECISION equity point;
3. give the provider a :class:`DecisionContext` (features up to ``t`` and a portfolio snapshot only);
4. turn its signal into an order that fills at the open of the 1m bar at ``t + latency``.

At the end of the window an open position is closed at the close of the last 1m bar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from arven.backtest.clock import HOUR_MS, SimulationClock
from arven.backtest.costs import require_taker_only
from arven.backtest.errors import ConfigurationError, DataError, SignalError
from arven.backtest.execution import Simulator
from arven.backtest.marketdata import MarketData
from arven.backtest.provider import DecisionContext, FeatureData, FeatureView, PortfolioSnapshot, PrepareInfo, SignalProvider
from arven.backtest.types import (
    EquityKind,
    EquityPoint,
    Fill,
    FundingEvent,
    Order,
    OrderEvent,
    OrderKind,
    Side,
    Trade,
)
from arven.core.backtest_config import BacktestConfig
from arven.core.config import AppConfig
from arven.core.sessions import SessionCalendar, session_decision_mask
from arven.core.splitguard import AllowedWindow
from arven.core.types import Action


@dataclass(frozen=True, eq=False)
class BacktestResult:
    period: str
    window_start_ms: int
    window_end_ms: int
    initial_equity: float
    final_wallet: float
    orders: tuple[OrderEvent, ...]
    fills: tuple[Fill, ...]
    funding: tuple[FundingEvent, ...]
    trades: tuple[Trade, ...]
    equity: tuple[EquityPoint, ...]
    low_points: tuple[tuple[int, float], ...]
    signal_counts: dict[str, int]
    n_decisions: int
    stress: bool


def decision_grid(window: AllowedWindow, calendar: SessionCalendar | None = None) -> np.ndarray:
    """Every 1h close in the window around the clock; a session market's tradable 1h closes only
    (:func:`arven.core.sessions.session_decision_mask`)."""
    grid = np.arange(window.start_ms, window.end_ms, HOUR_MS, dtype=np.int64)
    return grid if calendar is None or calendar.always_open else grid[session_decision_mask(calendar, grid)]


class Backtester:
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
        self._grid = decision_grid(window, app.session_calendar())
        if len(features.t_ms) != len(self._grid) or (len(self._grid) and np.any(features.t_ms != self._grid)):
            raise DataError("feature rows do not match the decision grid of the window")
        self.app, self.cfg, self.window, self.market, self.features, self.stress = app, cfg, window, market, features, stress

    def run(self, provider: SignalProvider) -> BacktestResult:
        md, cfg = self.market, self.cfg
        clock = SimulationClock(self._grid)
        view = FeatureView(self.features.t_ms, self.features.names, self.features.values, clock, self.features.first_ready_ms)
        provider.prepare(PrepareInfo(self._grid.copy(), self.window.end_ms, self.features.first_ready_ms))
        sim = Simulator(md, cfg, self.app.costs, stress=self.stress)
        counts = {"none": 0, "no_trade": 0, "entry": 0, "close": 0, "close_ignored": 0}
        next_order_id = 1
        cursor = 0
        n_decisions = 0

        while (t := clock.advance()) is not None:
            j = md.first_at_or_after(t)
            sim.run_window(cursor, j)
            cursor = j
            price = float(md.close[j - 1]) if j > 0 else None
            point = sim.add_point(t, price, EquityKind.DECISION)
            n_decisions += 1
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
            signal = provider.decide(DecisionContext(t, n_decisions - 1, view, snap, self.window.period.value))
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

        sim.run_window(cursor, len(md))
        sim.finish()
        return BacktestResult(
            period=self.window.period.value,
            window_start_ms=self.window.start_ms,
            window_end_ms=self.window.end_ms,
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
