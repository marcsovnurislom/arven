"""Immutable records and enums of the backtester.

Money is float64 (USDT); times are UTC epoch milliseconds. Records are frozen: state transitions create
new objects, and the ledgers are sequences of these records.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class Side(IntEnum):
    LONG = 1
    SHORT = -1


class OrderKind(StrEnum):
    ENTRY = "ENTRY"
    CLOSE = "CLOSE"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ExitReason(StrEnum):
    STOP = "STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_STOP = "TIME_STOP"
    SIGNAL_CLOSE = "SIGNAL_CLOSE"
    LIQUIDATION = "LIQUIDATION"
    DATA_GAP = "DATA_GAP"
    END_OF_PERIOD = "END_OF_PERIOD"


class FillPurpose(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    LIQUIDATION = "LIQUIDATION"


class EquityKind(StrEnum):
    DECISION = "DECISION"
    FILL = "FILL"
    FUNDING = "FUNDING"
    EXIT = "EXIT"
    FINAL = "FINAL"


@dataclass(frozen=True, slots=True)
class Order:
    order_id: int
    kind: OrderKind
    side: Side
    created_ms: int
    eligible_from_ms: int
    decision_equity: float
    notional_fraction: float | None
    stop_pct: float | None
    take_profit_pct: float | None
    max_holding_minutes: int | None
    tag: str


@dataclass(frozen=True, slots=True)
class OrderEvent:
    order_id: int
    time_ms: int
    status: OrderStatus
    reason: str  # "" when there is none
    detail: str  # deterministic key=value text with the numbers behind a rejection / fill


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: int
    order_id: int
    position_id: int
    time_ms: int
    bar_open_ms: int
    purpose: FillPurpose
    trade_side: int  # +1 buy, -1 sell
    qty: float
    ref_price: float
    fill_price: float
    slippage_bps: float
    fee: float


@dataclass(frozen=True, slots=True)
class FundingEvent:
    position_id: int
    time_ms: int
    rate: float
    rate_assumed: bool
    price: float
    qty: float
    cash_flow: float  # signed change of the wallet (negative = paid)


@dataclass(frozen=True, slots=True)
class Position:
    position_id: int
    order_id: int
    side: Side
    qty: float
    entry_ref_price: float
    entry_price: float
    entry_time_ms: int
    entry_index: int
    margin: float
    liquidation_price: float
    stop_price: float | None
    take_profit_price: float | None
    time_stop_ms: int | None
    entry_fee: float
    entry_slippage_cost: float
    funding_cash: float  # signed running total of funding cash flows
    decision_equity: float
    signal_ms: int
    tag: str


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: int
    side: int
    signal_ms: int
    entry_time_ms: int
    exit_time_ms: int
    entry_ref_price: float
    entry_price: float
    exit_ref_price: float
    exit_price: float
    qty: float
    notional_entry: float
    notional_exit: float
    margin: float
    decision_equity: float
    exit_reason: ExitReason
    gross_pnl: float  # at reference prices: side * qty * (exit_ref - entry_ref)
    slippage_cost: float
    fees: float
    funding: float  # signed cash flow, negative = paid
    liquidation_extra_loss: float  # loss of margin beyond the price move (0 unless liquidated)
    net_pnl: float
    return_on_equity: float
    r_multiple: float  # NaN without a stop
    minutes_held: float
    mae: float  # max adverse excursion in USDT (>= 0), from 1m extremes
    mfe: float  # max favourable excursion in USDT (>= 0)
    tag: str


@dataclass(frozen=True, slots=True)
class EquityPoint:
    time_ms: int
    wallet: float
    unrealized: float
    equity: float
    qty: float  # signed position quantity, 0 when flat
    margin: float
    kind: EquityKind


@dataclass(frozen=True, slots=True)
class AccountState:
    wallet: float
    position: Position | None = None
    cum_fees: float = 0.0
    cum_slippage: float = 0.0
    cum_funding: float = 0.0  # signed
    cum_gross: float = 0.0
    cum_net: float = 0.0
    next_position_id: int = 1
    next_fill_id: int = 1
