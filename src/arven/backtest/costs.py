"""Fee and slippage arithmetic (pure). Parameters come from ``costs.yaml`` (:class:`CostsConfig`)."""

from __future__ import annotations

from arven.backtest.errors import ConfigurationError
from arven.core.config import CostsConfig


def require_taker_only(costs: CostsConfig) -> None:
    """Stage 4 models market orders only: a maker fill-probability model is out of scope."""
    f = costs.fees
    if not (f.entry_order_type == f.exit_order_type == f.stop_order_type == "taker"):
        raise ConfigurationError("Stage 4 supports taker orders only (costs.yaml fees.*_order_type must be 'taker')")


def taker_fee_rate(costs: CostsConfig) -> float:
    return costs.fees.taker_fee_bps / 1e4


def slippage_fraction(open_: float, high: float, low: float, costs: CostsConfig, stress: bool) -> float:
    """Adverse price impact as a fraction of price: ``s * (fixed_bps + k * bar_range_bps) / 1e4``.

    The range is that of the 1m bar in which the order executes (an execution-model quantity; it is never a
    decision input). ``s`` is ``stress_multiplier`` in stress runs, otherwise 1.
    """
    range_bps = 1e4 * (high - low) / open_
    s = costs.slippage.stress_multiplier if stress else 1.0
    return s * (costs.slippage.fixed_bps + costs.slippage.volatility_multiplier * range_bps) / 1e4


def adverse_price(ref_price: float, trade_side: int, sigma: float) -> float:
    """Fill price after slippage: buyers (+1) pay more, sellers (-1) receive less."""
    return ref_price * (1.0 + trade_side * sigma)
