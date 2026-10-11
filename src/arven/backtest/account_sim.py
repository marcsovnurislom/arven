"""A simple dollar account replay of already-resolved trades (the owner's "how would $1000 have done" view).

Pure post-processing: each trade's net R (costs already included) is turned into dollars with a position size chosen
from the equity at the moment the trade opens. Sizing rule (owner, 2026-10-11): risk ``risk_fraction`` of the current
equity; the size is rounded *down* to the broker's lot step; if that is below the minimum lot, the minimum lot is used
only while its loss at the stop stays within ``max_loss_fraction`` of equity, otherwise the trade is skipped. Trades
must be given in time order and must not overlap (one open trade at a time), so the equity at each entry is known.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountRules:
    start_equity: float = 1000.0
    risk_fraction: float = 0.01
    min_lot: float = 0.01  # BTC
    lot_step: float = 0.01  # BTC
    max_loss_fraction: float = 0.05


@dataclass(frozen=True, slots=True)
class TradeForAccount:
    """One trade: ``risk_per_unit`` = |entry - stop| in $ per 1 BTC; ``net_r`` = result per unit of that risk."""

    risk_per_unit: float
    net_r: float


@dataclass(frozen=True, slots=True)
class AccountStep:
    size: float  # BTC; 0 if skipped
    risk_usd: float  # $ lost if the stop is hit (before costs)
    pnl_usd: float
    equity_after: float
    skipped: str | None = None


def replay_account(trades: list[TradeForAccount], rules: AccountRules = AccountRules()) -> list[AccountStep]:
    equity = rules.start_equity
    out: list[AccountStep] = []
    for t in trades:
        if not (math.isfinite(t.risk_per_unit) and t.risk_per_unit > 0 and equity > 0):
            out.append(AccountStep(0.0, 0.0, 0.0, equity, "invalid"))
            continue
        size = math.floor(round(equity * rules.risk_fraction / t.risk_per_unit / rules.lot_step, 9)) * rules.lot_step
        if size < rules.min_lot:
            if rules.min_lot * t.risk_per_unit > equity * rules.max_loss_fraction:
                out.append(AccountStep(0.0, 0.0, 0.0, equity, "min_lot_risk_above_limit"))
                continue
            size = rules.min_lot
        size = round(size, 8)
        pnl = size * t.risk_per_unit * t.net_r
        equity += pnl
        out.append(AccountStep(size, size * t.risk_per_unit, pnl, equity))
    return out


def summarize_account(steps: list[AccountStep], rules: AccountRules = AccountRules()) -> dict[str, float | int]:
    taken = [s for s in steps if s.skipped is None]
    curve = [rules.start_equity] + [s.equity_after for s in steps]
    peak, max_dd = curve[0], 0.0
    for e in curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak if peak > 0 else 0.0)
    return {
        "start_equity": rules.start_equity, "final_equity": curve[-1], "return": curve[-1] / rules.start_equity - 1.0,
        "trades": len(taken), "skipped": len(steps) - len(taken), "wins": sum(1 for s in taken if s.pnl_usd > 0),
        "losses": sum(1 for s in taken if s.pnl_usd <= 0), "max_drawdown": max_dd,
        "best_trade_usd": max((s.pnl_usd for s in taken), default=0.0), "worst_trade_usd": min((s.pnl_usd for s in taken), default=0.0),
    }
