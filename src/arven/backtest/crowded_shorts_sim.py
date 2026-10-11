"""Crowded Shorts execution on 1m bars: one hold block -> one long trade, in R, net of costs.

The same arithmetic as the research script that produced the pre-registered and sealed-test numbers
(``scripts/research/cs_sealed_test.py``, ``simulate`` with CFD costs, no funding): market buy at the open of the entry
minute with the cost model's adverse slippage; the stop ``stop_fraction`` below that fill, checked on every 1m bar
before the planned exit (a bar opening below the stop fills at its open); otherwise out at the open of the planned
exit minute. Fees on both sides at the taker rate. Rules: :mod:`arven.engine.strategy_crowded_shorts`.

Unlike the research script, a block whose exit has not happened yet is reported as still open (``closed=False``)
instead of being skipped - the live loop needs that state; a closed block gives exactly the research result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.marketdata import MarketData
from arven.core.config import CostsConfig
from arven.engine.strategy_crowded_shorts import CrowdedShortsBlock


@dataclass(frozen=True, slots=True)
class CrowdedShortsTrade:
    entry_ms: int
    entry: float  # the fill
    stop: float
    closed: bool
    exit_ms: int | None = None
    exit: float | None = None
    reason: str | None = None  # "STOP" | "TIME"
    r: float | None = None  # net R (risk = entry - stop)


def resolve_block(block: CrowdedShortsBlock, market: MarketData, costs: CostsConfig, stop_fraction: float, stress: bool = False) -> CrowdedShortsTrade | None:
    """``None`` if the entry minute is not in ``market`` (missing data, or not reached yet) - no trade."""
    T, O, H, L = market.time_ms, market.open, market.high, market.low
    i0 = int(np.searchsorted(T, block.start_ms))
    if i0 >= len(T) or int(T[i0]) != block.start_ms:
        return None
    entry = adverse_price(float(O[i0]), 1, slippage_fraction(float(O[i0]), float(H[i0]), float(L[i0]), costs, stress))
    stop = entry * (1.0 - stop_fraction)
    i1 = len(T) if block.end_ms is None else int(np.searchsorted(T, block.end_ms))
    hit = np.flatnonzero(L[i0:i1] <= stop)
    if hit.size:
        j = i0 + int(hit[0])
        ref, reason = min(stop, float(O[j])), "STOP"
    elif block.end_ms is not None and i1 < len(T):
        j, ref, reason = i1, float(O[i1]), "TIME"
    else:
        return CrowdedShortsTrade(block.start_ms, entry, stop, closed=False)
    exit_ = adverse_price(ref, -1, slippage_fraction(float(O[j]), float(H[j]), float(L[j]), costs, stress))
    fee = taker_fee_rate(costs)
    pnl = exit_ - entry - fee * (entry + exit_)
    return CrowdedShortsTrade(block.start_ms, entry, stop, True, int(T[j]), exit_, reason, pnl / (entry - stop))


__all__ = ["CrowdedShortsTrade", "resolve_block"]
