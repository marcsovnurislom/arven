"""1m execution simulator.

``Simulator`` owns the account state and the ledgers and advances it over 1m bars. Only bars where
something can happen are processed (fills, funding, time stops, barrier touches, data gaps); everything in
between is skipped with numpy searches, and the result is identical to walking every bar (verified against a
naive per-bar reference in ``tests/backtest/test_oracle.py``).

Event order at one bar open ``tau`` (documented in docs/current_state.md):

1. funding settlement for funding times <= tau, for a position opened before ``tau``;
2. liquidation, then gap-through stop, then data-gap exit, then scheduled exits (time stop, close order) at the open;
3. the pending entry fill at this open (only when flat);
4. intrabar extremes of this bar for the open position (including one filled at this open).

Intrabar rules: adverse levels (stop, liquidation) are processed in price order (the one nearer the entry
first) and always beat the take-profit in the same bar; a stop gapped through at the open fills at the open.
Exit times are the open time of the bar in which the exit happened (the order inside a minute is unknown).
"""

from __future__ import annotations

import math

import numpy as np

from arven.backtest.accounting import ExitOutcome, apply_funding, enter, exit_position, mark
from arven.backtest.errors import DataError
from arven.backtest.marketdata import MarketData
from arven.backtest.types import (
    AccountState,
    EquityKind,
    EquityPoint,
    ExitReason,
    Fill,
    FundingEvent,
    Order,
    OrderEvent,
    OrderKind,
    OrderStatus,
    Trade,
)
from arven.core.backtest_config import BacktestConfig
from arven.core.config import CostsConfig


class Simulator:
    def __init__(self, md: MarketData, cfg: BacktestConfig, costs: CostsConfig, *, stress: bool = False) -> None:
        self.md = md
        self.cfg = cfg
        self.costs = costs
        self.stress = stress
        self.state = AccountState(wallet=cfg.initial_equity_usdt)
        self.pending_entry: tuple[Order, int] | None = None
        self.pending_close: tuple[Order, int] | None = None
        self.fund_i = 0
        self.order_events: list[OrderEvent] = []
        self.fills: list[Fill] = []
        self.funding_events: list[FundingEvent] = []
        self.trades: list[Trade] = []
        self.equity: list[EquityPoint] = []
        self.low_points: list[tuple[int, float]] = []  # (time_ms, worst-case equity while a position was open)
        self._gap_flag = np.zeros(len(md), dtype=bool)
        self._gap_flag[md.gap_indices] = True
        self._seg_start: int | None = None  # first bar of the current worst-case-equity segment
        self._seg_wallet = 0.0

    # ------------------------------------------------------------------ orders

    def submit(self, order: Order) -> None:
        """Register an order created at decision time; it fills at the 1m bar at ``eligible_from_ms``."""
        self.order_events.append(OrderEvent(order.order_id, order.created_ms, OrderStatus.CREATED, "", f"kind={order.kind.value}"))
        j = self.md.index_of(order.eligible_from_ms)
        if j < 0:
            self.order_events.append(
                OrderEvent(order.order_id, order.created_ms, OrderStatus.CANCELLED, "no_market_data", f"eligible_from={order.eligible_from_ms}")
            )
            return
        if order.kind == OrderKind.ENTRY:
            self.pending_entry = (order, j)
        else:
            self.pending_close = (order, j)

    def reject(self, order: Order, reason: str, detail: str = "") -> None:
        self.order_events.append(OrderEvent(order.order_id, order.created_ms, OrderStatus.CREATED, "", f"kind={order.kind.value}"))
        self.order_events.append(OrderEvent(order.order_id, order.created_ms, OrderStatus.REJECTED, reason, detail))

    # ------------------------------------------------------------------ marking

    def add_point(self, time_ms: int, price: float | None, kind: EquityKind) -> EquityPoint:
        pos = self.state.position
        unrealized, equity = mark(self.state, price) if price is not None else (0.0, self.state.wallet)
        point = EquityPoint(
            time_ms,
            self.state.wallet,
            unrealized,
            equity,
            0.0 if pos is None else int(pos.side) * pos.qty,
            0.0 if pos is None else pos.margin,
            kind,
        )
        self.equity.append(point)
        return point

    # ------------------------------------------------------------------ window loop

    def run_window(self, a: int, b: int) -> None:
        """Process the 1m bars with index in ``[a, b)``."""
        if b <= a:
            return
        if self.state.position is not None:
            self._seg_start, self._seg_wallet = a, self.state.wallet
        j = a
        while j < b:
            k = self._next_event(j, b)
            if k < 0:
                break
            self.process_bar(k)
            j = k + 1
        pos = self.state.position
        if pos is not None and self._seg_start is not None:
            self._record_low(pos.side, pos.qty, pos.entry_price, self._seg_wallet, self._seg_start, b - 1)

    def _record_low(self, side: int, qty: float, entry_price: float, wallet: float, first: int, last: int) -> None:
        if last < first:
            return
        d = int(side)
        worst = float(self.md.low[first : last + 1].min()) if d > 0 else float(self.md.high[first : last + 1].max())
        self.low_points.append((int(self.md.time_ms[last]), wallet + d * qty * (worst - entry_price)))

    def _next_event(self, j: int, b: int) -> int:
        md = self.md
        best = b
        if self.pending_entry is not None:
            fi = self.pending_entry[1]
            if j <= fi < b:
                best = min(best, fi)
        pos = self.state.position
        if pos is None:
            return best if best < b else -1
        if self.pending_close is not None:
            fi = self.pending_close[1]
            if fi < b:
                best = min(best, max(fi, j))
        if pos.side > 0:
            cond = md.low[j:b] <= pos.liquidation_price
            if pos.stop_price is not None:
                cond |= md.low[j:b] <= pos.stop_price
            if pos.take_profit_price is not None:
                cond |= md.high[j:b] >= pos.take_profit_price
        else:
            cond = md.high[j:b] >= pos.liquidation_price
            if pos.stop_price is not None:
                cond |= md.high[j:b] >= pos.stop_price
            if pos.take_profit_price is not None:
                cond |= md.low[j:b] <= pos.take_profit_price
        if cond.any():
            best = min(best, j + int(cond.argmax()))
        if pos.time_stop_ms is not None:
            jt = md.first_at_or_after(pos.time_stop_ms)
            if jt < b:
                best = min(best, max(jt, j))
        if self.fund_i < len(md.funding_time_ms):
            k = self.fund_i
            fi = int(md.funding_bar_index[k])
            if fi < 0:
                fi = md.first_at_or_after(int(md.funding_time_ms[k]))
            if fi < b:
                best = min(best, max(fi, j))
        gi = int(np.searchsorted(md.gap_indices, j))
        if gi < len(md.gap_indices) and md.gap_indices[gi] < b:
            best = min(best, int(md.gap_indices[gi]))
        return best if best < b else -1

    # ------------------------------------------------------------------ per-bar logic

    def process_bar(self, j: int) -> None:
        md = self.md
        tau = int(md.time_ms[j])
        o, h, l = float(md.open[j]), float(md.high[j]), float(md.low[j])  # noqa: E741

        pos = self.state.position
        if pos is not None:
            self._settle_funding(tau, o)
            pos = self.state.position

        if pos is not None and pos.entry_time_ms < tau:
            d = int(pos.side)
            if (d > 0 and o <= pos.liquidation_price) or (d < 0 and o >= pos.liquidation_price):
                return self._exit(j, o, ExitReason.LIQUIDATION, at_open=True)
            s = pos.stop_price
            if s is not None and ((d > 0 and o <= s) or (d < 0 and o >= s)):
                return self._exit(j, o, ExitReason.STOP, at_open=True)
            if self._gap_flag[j]:
                return self._exit(j, o, ExitReason.DATA_GAP, at_open=True)
            if pos.time_stop_ms is not None and tau >= pos.time_stop_ms:
                return self._exit(j, o, ExitReason.TIME_STOP, at_open=True)
            if self.pending_close is not None and j >= self.pending_close[1]:
                return self._exit(j, o, ExitReason.SIGNAL_CLOSE, at_open=True)
        elif self.pending_close is not None and j >= self.pending_close[1]:
            order, _ = self.pending_close
            self.pending_close = None
            self.order_events.append(OrderEvent(order.order_id, tau, OrderStatus.CANCELLED, "no_position", ""))

        if self.pending_entry is not None and self.state.position is None and j == self.pending_entry[1]:
            order, _ = self.pending_entry
            self.pending_entry = None
            outcome = enter(
                self.state, order, time_ms=tau, bar_index=j, o=o, h=h, l=l, cfg=self.cfg, costs=self.costs, stress=self.stress
            )
            self.order_events.append(outcome.event)
            self.state = outcome.state
            if outcome.fill is not None:
                self.fills.append(outcome.fill)
                self.fund_i = int(np.searchsorted(md.funding_time_ms, tau, side="right"))
                self._seg_start, self._seg_wallet = j, self.state.wallet
                self.add_point(tau, o, EquityKind.FILL)

        pos = self.state.position
        if pos is None:
            return
        d, ref, reason = int(pos.side), None, None
        s, t, lp = pos.stop_price, pos.take_profit_price, pos.liquidation_price
        if d > 0:
            hit_liq, hit_stop, hit_tp = l <= lp, s is not None and l <= s, t is not None and h >= t
            liq_first = hit_liq and (not hit_stop or lp >= s)  # type: ignore[operator]
        else:
            hit_liq, hit_stop, hit_tp = h >= lp, s is not None and h >= s, t is not None and l <= t
            liq_first = hit_liq and (not hit_stop or lp <= s)  # type: ignore[operator]
        if liq_first:
            ref, reason = lp, ExitReason.LIQUIDATION
        elif hit_stop:
            ref, reason = s, ExitReason.STOP
        elif hit_tp:
            ref, reason = t, ExitReason.TAKE_PROFIT
        if reason is not None:
            self._exit(j, float(ref), reason, at_open=False)  # type: ignore[arg-type]

    def _settle_funding(self, tau: int, open_price: float) -> None:
        md, ft = self.md, self.md.funding_time_ms
        policy = self.costs.funding.missing_policy
        while self.fund_i < len(ft) and int(ft[self.fund_i]) <= tau and self.state.position is not None:
            k = self.fund_i
            t_fund = int(ft[k])
            rate, assumed = float(md.funding_rate[k]), False
            if math.isnan(rate):
                if policy == "error":
                    raise DataError(f"missing funding rate at {t_fund} while a position is open")
                rate, assumed = self.costs.funding.assumed_rate_bps / 1e4, True
            bar = int(md.funding_bar_index[k])
            if bar >= 0:
                price = float(md.open[bar])
            elif policy == "error":
                raise DataError(f"no 1m bar at funding time {t_fund} while a position is open")
            else:
                price = open_price
            self.state, event = apply_funding(self.state, time_ms=t_fund, rate=rate, rate_assumed=assumed, price=price, cfg=self.cfg)
            self.funding_events.append(event)
            self.add_point(t_fund, price, EquityKind.FUNDING)
            self.fund_i += 1

    def _exit(self, j: int, ref: float, reason: ExitReason, *, at_open: bool) -> None:
        md = self.md
        pos = self.state.position
        assert pos is not None
        tau = int(md.time_ms[j])
        end = j if at_open else j + 1
        end = max(end, pos.entry_index + 1)
        lo = float(md.low[pos.entry_index : end].min())
        hi = float(md.high[pos.entry_index : end].max())
        d = int(pos.side)
        mae = max(0.0, (pos.entry_price - lo) if d > 0 else (hi - pos.entry_price)) * pos.qty
        mfe = max(0.0, (hi - pos.entry_price) if d > 0 else (pos.entry_price - lo)) * pos.qty
        first = pos.entry_index if self._seg_start is None else self._seg_start
        self._record_low(pos.side, pos.qty, pos.entry_price, self._seg_wallet, first, j - 1 if at_open else j)
        self._seg_start = None
        close_order = self.pending_close[0] if self.pending_close is not None else None
        order_id = close_order.order_id if (reason == ExitReason.SIGNAL_CLOSE and close_order is not None) else pos.order_id
        outcome: ExitOutcome = exit_position(
            self.state,
            time_ms=tau,
            bar_open_ms=tau,
            ref_price=ref,
            o=float(md.open[j]),
            h=float(md.high[j]),
            l=float(md.low[j]),
            reason=reason,
            order_id=order_id,
            mae=mae,
            mfe=mfe,
            costs=self.costs,
            cfg=self.cfg,
            stress=self.stress,
        )
        self.state = outcome.state
        self.fills.append(outcome.fill)
        self.trades.append(outcome.trade)
        if close_order is not None:
            self.pending_close = None
            if reason == ExitReason.SIGNAL_CLOSE:
                self.order_events.append(OrderEvent(close_order.order_id, tau, OrderStatus.FILLED, "", f"price={outcome.fill.fill_price:.8f}"))
            else:
                self.order_events.append(OrderEvent(close_order.order_id, tau, OrderStatus.CANCELLED, "position_closed", reason.value))
        self.add_point(tau, None, EquityKind.EXIT)

    # ------------------------------------------------------------------ end of window

    def finish(self) -> None:
        """Close any open position at the close of the last 1m bar and record the final equity point."""
        md = self.md
        n = len(md)
        if self.pending_entry is not None:
            order, _ = self.pending_entry
            self.pending_entry = None
            self.order_events.append(OrderEvent(order.order_id, md.window_end_ms, OrderStatus.CANCELLED, "window_end", ""))
        if self.pending_close is not None:
            order, _ = self.pending_close
            self.pending_close = None
            self.order_events.append(OrderEvent(order.order_id, md.window_end_ms, OrderStatus.CANCELLED, "window_end", ""))
        pos = self.state.position
        if pos is not None and n > 0:
            j = n - 1
            d = int(pos.side)
            lo = float(md.low[pos.entry_index : n].min())
            hi = float(md.high[pos.entry_index : n].max())
            mae = max(0.0, (pos.entry_price - lo) if d > 0 else (hi - pos.entry_price)) * pos.qty
            mfe = max(0.0, (hi - pos.entry_price) if d > 0 else (pos.entry_price - lo)) * pos.qty
            outcome = exit_position(
                self.state,
                time_ms=md.window_end_ms,
                bar_open_ms=int(md.time_ms[j]),
                ref_price=float(md.close[j]),
                o=float(md.open[j]),
                h=float(md.high[j]),
                l=float(md.low[j]),
                reason=ExitReason.END_OF_PERIOD,
                order_id=pos.order_id,
                mae=mae,
                mfe=mfe,
                costs=self.costs,
                cfg=self.cfg,
                stress=self.stress,
            )
            self.state = outcome.state
            self.fills.append(outcome.fill)
            self.trades.append(outcome.trade)
            self.add_point(md.window_end_ms, None, EquityKind.EXIT)
        self.add_point(md.window_end_ms, None, EquityKind.FINAL)

