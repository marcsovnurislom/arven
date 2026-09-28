"""Portfolio accounting as pure state transitions.

Equations (d = +1 long / -1 short, q = quantity, all money in USDT):

    entry fill      P_e = o * (1 + d * sigma)              sigma = slippage_fraction of the fill bar
    notional        N_e = q * P_e                          q = floor(f * E_t / P_e / step) * step
    margin          M   = N_e / L                          (isolated)
    entry fee       Fee_e = taker_rate * N_e               paid from the wallet
    unrealized      U(P) = d * q * (P - P_e)
    equity          E = W + U(P)                           W = wallet incl. realized PnL, fees, funding
    funding         cash flow = -d * q * P_T * r_T         negative when paid
    exit fill       P_x = P_ref_x * (1 - d * sigma_x)      Fee_x = taker_rate * q * P_x
    net PnL         gross_ref - slippage - fees + funding  gross_ref = d * q * (P_ref_x - P_ref_e)
    liquidation     wallet loses the position margin M (or M + funding if funding is debited from the margin);
                    no exit fee or extra slippage

All transitions return new frozen objects; nothing here touches market data or time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.margin import initial_margin, liquidation_price, liquidation_price_from_margin, qty_from_notional
from arven.backtest.types import (
    AccountState,
    ExitReason,
    Fill,
    FillPurpose,
    FundingEvent,
    Order,
    OrderEvent,
    OrderStatus,
    Position,
    Trade,
)
from arven.core.backtest_config import BacktestConfig
from arven.core.config import CostsConfig


@dataclass(frozen=True, slots=True)
class EntryOutcome:
    state: AccountState
    fill: Fill | None
    event: OrderEvent


@dataclass(frozen=True, slots=True)
class ExitOutcome:
    state: AccountState
    fill: Fill
    trade: Trade


def mark(state: AccountState, price: float) -> tuple[float, float]:
    """Return ``(unrealized, equity)`` at mark ``price``."""
    pos = state.position
    if pos is None:
        return 0.0, state.wallet
    unrealized = int(pos.side) * pos.qty * (price - pos.entry_price)
    return unrealized, state.wallet + unrealized


def _reject(state: AccountState, order: Order, time_ms: int, reason: str, detail: str) -> EntryOutcome:
    return EntryOutcome(state, None, OrderEvent(order.order_id, time_ms, OrderStatus.REJECTED, reason, detail))


def enter(
    state: AccountState,
    order: Order,
    *,
    time_ms: int,
    bar_index: int,
    o: float,
    h: float,
    l: float,  # noqa: E741
    cfg: BacktestConfig,
    costs: CostsConfig,
    stress: bool,
) -> EntryOutcome:
    """Fill (or reject) an entry order at the open of the fill bar."""
    d = int(order.side)
    sigma = slippage_fraction(o, h, l, costs, stress)
    p_e = adverse_price(o, d, sigma)
    assert order.notional_fraction is not None
    q = qty_from_notional(order.notional_fraction * order.decision_equity, p_e, cfg.qty_step_btc)
    notional = q * p_e
    if q <= 0.0 or notional < cfg.min_notional_usdt:
        return _reject(state, order, time_ms, "below_min_notional", f"notional={notional:.8f};min={cfg.min_notional_usdt:.8f}")

    stop_price = None
    if order.stop_pct is not None:
        stop_price = p_e * (1.0 - d * order.stop_pct)
        # A stop that is not on the loss side of the reference price would be triggered by the fill itself.
        if (d > 0 and stop_price >= o) or (d < 0 and stop_price <= o):
            return _reject(state, order, time_ms, "invalid_stop", f"stop={stop_price:.8f};ref={o:.8f};slippage={sigma:.10f}")
    take_profit_price = None if order.take_profit_pct is None else p_e * (1.0 + d * order.take_profit_pct)

    fee = taker_fee_rate(costs) * notional
    margin = initial_margin(notional, cfg.leverage)
    if margin + fee > state.wallet:
        return _reject(
            state, order, time_ms, "insufficient_margin", f"margin={margin:.8f};fee={fee:.8f};wallet={state.wallet:.8f}"
        )

    position = Position(
        position_id=state.next_position_id,
        order_id=order.order_id,
        side=order.side,
        qty=q,
        entry_ref_price=o,
        entry_price=p_e,
        entry_time_ms=time_ms,
        entry_index=bar_index,
        margin=margin,
        liquidation_price=liquidation_price(d, p_e, cfg.leverage, cfg.maintenance_margin_rate),
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        time_stop_ms=None if order.max_holding_minutes is None else time_ms + order.max_holding_minutes * 60_000,
        entry_fee=fee,
        entry_slippage_cost=q * o * sigma,
        funding_cash=0.0,
        decision_equity=order.decision_equity,
        signal_ms=order.created_ms,
        tag=order.tag,
    )
    fill = Fill(
        fill_id=state.next_fill_id,
        order_id=order.order_id,
        position_id=position.position_id,
        time_ms=time_ms,
        bar_open_ms=time_ms,
        purpose=FillPurpose.ENTRY,
        trade_side=d,
        qty=q,
        ref_price=o,
        fill_price=p_e,
        slippage_bps=sigma * 1e4,
        fee=fee,
    )
    new_state = replace(
        state,
        wallet=state.wallet - fee,
        position=position,
        next_position_id=state.next_position_id + 1,
        next_fill_id=state.next_fill_id + 1,
    )
    event = OrderEvent(order.order_id, time_ms, OrderStatus.FILLED, "", f"qty={q:.8f};price={p_e:.8f};notional={notional:.8f}")
    return EntryOutcome(new_state, fill, event)


def apply_funding(
    state: AccountState, *, time_ms: int, rate: float, rate_assumed: bool, price: float, cfg: BacktestConfig
) -> tuple[AccountState, FundingEvent]:
    """Settle one funding payment. With ``liquidation_includes_funding`` the payment is debited from the position's
    isolated margin, so the liquidation price moves with the margin balance."""
    pos = state.position
    assert pos is not None
    cash = -int(pos.side) * pos.qty * price * rate
    event = FundingEvent(pos.position_id, time_ms, rate, rate_assumed, price, pos.qty, cash)
    funding_cash = pos.funding_cash + cash
    new_pos = replace(pos, funding_cash=funding_cash)
    if cfg.liquidation_includes_funding:
        new_pos = replace(
            new_pos,
            liquidation_price=liquidation_price_from_margin(
                int(pos.side), pos.entry_price, pos.qty, pos.margin + funding_cash, cfg.maintenance_margin_rate
            ),
        )
    return replace(state, wallet=state.wallet + cash, position=new_pos, cum_funding=state.cum_funding + cash), event


def exit_position(
    state: AccountState,
    *,
    time_ms: int,
    bar_open_ms: int,
    ref_price: float,
    o: float,
    h: float,
    l: float,  # noqa: E741
    reason: ExitReason,
    order_id: int,
    mae: float,
    mfe: float,
    costs: CostsConfig,
    cfg: BacktestConfig,
    stress: bool,
) -> ExitOutcome:
    """Close the whole position at ``ref_price`` (before slippage); liquidation loses the isolated margin.

    With ``liquidation_includes_funding`` the margin balance at liquidation is ``margin + funding`` (funding was
    debited from it), so the wallet loses ``max(margin + funding, 0)`` on top of what funding already took.
    """
    pos = state.position
    assert pos is not None
    d, q = int(pos.side), pos.qty
    gross = d * q * (ref_price - pos.entry_ref_price)

    if reason == ExitReason.LIQUIDATION:
        fill_price, fee_x, sigma_x, purpose = ref_price, 0.0, 0.0, FillPurpose.LIQUIDATION
        confiscated = max(pos.margin + pos.funding_cash, 0.0) if cfg.liquidation_includes_funding else pos.margin
        wallet = state.wallet - confiscated
        slippage = pos.entry_slippage_cost
        fees = pos.entry_fee
        net = -confiscated - pos.entry_fee + pos.funding_cash
        liq_extra = net - (gross - slippage - fees + pos.funding_cash)
        notional_exit = q * ref_price
    else:
        sigma_x = slippage_fraction(o, h, l, costs, stress)
        fill_price = adverse_price(ref_price, -d, sigma_x)
        fee_x = taker_fee_rate(costs) * q * fill_price
        wallet = state.wallet + d * q * (fill_price - pos.entry_price) - fee_x
        slippage = pos.entry_slippage_cost + q * ref_price * sigma_x
        fees = pos.entry_fee + fee_x
        net = gross - slippage - fees + pos.funding_cash
        liq_extra = 0.0
        purpose = FillPurpose.EXIT
        notional_exit = q * fill_price

    fill = Fill(
        fill_id=state.next_fill_id,
        order_id=order_id,
        position_id=pos.position_id,
        time_ms=time_ms,
        bar_open_ms=bar_open_ms,
        purpose=purpose,
        trade_side=-d,
        qty=q,
        ref_price=ref_price,
        fill_price=fill_price,
        slippage_bps=sigma_x * 1e4,
        fee=fee_x,
    )
    risk = None if pos.stop_price is None else q * abs(pos.entry_price - pos.stop_price)
    trade = Trade(
        trade_id=pos.position_id,
        side=d,
        signal_ms=pos.signal_ms,
        entry_time_ms=pos.entry_time_ms,
        exit_time_ms=time_ms,
        entry_ref_price=pos.entry_ref_price,
        entry_price=pos.entry_price,
        exit_ref_price=ref_price,
        exit_price=fill_price,
        qty=q,
        notional_entry=q * pos.entry_price,
        notional_exit=notional_exit,
        margin=pos.margin,
        decision_equity=pos.decision_equity,
        exit_reason=reason,
        gross_pnl=gross,
        slippage_cost=slippage,
        fees=fees,
        funding=pos.funding_cash,
        liquidation_extra_loss=liq_extra,
        net_pnl=net,
        return_on_equity=net / pos.decision_equity,
        r_multiple=math.nan if not risk else net / risk,
        minutes_held=(time_ms - pos.entry_time_ms) / 60_000.0,
        mae=mae,
        mfe=mfe,
        tag=pos.tag,
    )
    new_state = replace(
        state,
        wallet=wallet,
        position=None,
        cum_fees=state.cum_fees + fees,
        cum_slippage=state.cum_slippage + slippage,
        cum_gross=state.cum_gross + gross,
        cum_net=state.cum_net + net,
        next_fill_id=state.next_fill_id + 1,
    )
    return ExitOutcome(new_state, fill, trade)
