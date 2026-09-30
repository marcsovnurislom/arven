"""Triple-barrier labels, resolved on 1m bars (docs/architecture.md section 11).

Forward-looking by definition (a label must look at what happened *after* the signal) — this is the one
place in ARVEN allowed to do that (CLAUDE.md/architecture rule 6: "labels live only in `ml/labels`, are
explicitly forward-looking, and can never be imported by `features/`"; enforced by
``tests/leakage/test_ml_leakage.py``'s import-boundary check). Nothing here is imported by
``arven.features`` or any Stage 3-5 module.

Reuses the exact pure cost functions Stage 4/5 already use (``arven.backtest.costs``: fee rate, slippage
fraction, adverse-price) so the label's definition of "profitable" shares one source of truth with real
execution. It deliberately does **not** import ``arven.backtest.execution``/``engine``/``accounting`` — this
is a standalone barrier resolver for *labeling*, not a second execution engine; see the module-level
simplifications noted below.

Known, documented simplifications relative to the real Stage 4 engine (not bugs):
- No gap-through adjustment: an exit that gaps past the stop/target level is still labeled at the barrier
  level itself, not the (worse) gapped-through price. Real execution can therefore be slightly worse than a
  label implies on a gap bar. Flagged in docs/current_state.md.
- No funding cost: funding is a materially smaller cost component than price movement, fees and slippage at
  these holding horizons (confirmed by the Stage 5 real backtest, where funding was `-7.04` of `~1500`
  total costs), and folding it in would require reading `funding_rates` inside the labeler as well as 1m
  bars, which architecture describes only as "resolved on 1m bars". Omitted, not hidden.
- No liquidation modeling: a Stage 5 meta-filter candidate's stop is always well inside the liquidation
  distance (risk rule 8), so within the labeling horizon liquidation is not a realistic outcome to model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.marketdata import MarketData
from arven.core.config import CostsConfig

MINUTE_MS = 60_000

Outcome = Literal["TP", "SL", "TIME"]


@dataclass(frozen=True, slots=True)
class LabelResult:
    outcome: Outcome
    entry_time_ms: int
    entry_price: float
    exit_time_ms: int
    exit_ref_price: float
    exit_price: float
    net_return: float  # signed fractional return, net of fees and slippage (not funding - see module docstring)
    label: int  # 1 if outcome == "TP" and net_return > min_net_return_for_positive_label, else 0


def resolve_triple_barrier(
    market: MarketData,
    fill_time_ms: int,
    direction: int,
    stop_pct: float,
    take_profit_pct: float,
    max_holding_minutes: int,
    costs: CostsConfig,
    min_net_return_for_positive_label: float,
) -> LabelResult | None:
    """Resolve one candidate's outcome. Returns ``None`` if the fill bar or the full horizon's 1m data is
    not available in ``market`` (the caller treats this as "not eligible for the dataset", not as label 0)."""
    if direction not in (1, -1):
        raise ValueError("direction must be +1 or -1")
    if not (math.isfinite(stop_pct) and stop_pct > 0 and math.isfinite(take_profit_pct) and take_profit_pct > 0):
        raise ValueError("stop_pct and take_profit_pct must be finite and positive")

    fill_idx = market.index_of(fill_time_ms)
    if fill_idx < 0:
        return None
    n = len(market)
    o, h, l, c, t = market.open, market.high, market.low, market.close, market.time_ms  # noqa: E741

    sigma_e = slippage_fraction(o[fill_idx], h[fill_idx], l[fill_idx], costs, stress=False)
    entry_price = adverse_price(o[fill_idx], direction, sigma_e)
    stop_level = entry_price * (1 - direction * stop_pct)
    tp_level = entry_price * (1 + direction * take_profit_pct)

    deadline_ms = int(t[fill_idx]) + max_holding_minutes * MINUTE_MS
    time_idx = int(np.searchsorted(t, deadline_ms))  # first bar at/after the deadline (time-barrier bar)
    if time_idx > n - 1 and int(t[-1]) < deadline_ms:
        return None  # the horizon runs past the end of the available 1m data: not resolvable
    time_idx = min(time_idx, n - 1)
    if time_idx < fill_idx:
        time_idx = fill_idx

    outcome: Outcome | None = None
    exit_idx = time_idx
    ref_price = float(c[time_idx])
    for j in range(fill_idx, time_idx + 1):
        hit_stop = (l[j] <= stop_level) if direction > 0 else (h[j] >= stop_level)
        hit_tp = (h[j] >= tp_level) if direction > 0 else (l[j] <= tp_level)
        if hit_stop:  # same-bar tie -> stop first, matching the Stage 4 execution convention
            outcome, exit_idx, ref_price = "SL", j, stop_level
            break
        if hit_tp:
            outcome, exit_idx, ref_price = "TP", j, tp_level
            break
    if outcome is None:
        outcome = "TIME"

    sigma_x = slippage_fraction(o[exit_idx], h[exit_idx], l[exit_idx], costs, stress=False)
    exit_price = adverse_price(ref_price, -direction, sigma_x)
    fee_rate = taker_fee_rate(costs)
    net_return = direction * (exit_price - entry_price) / entry_price - 2.0 * fee_rate

    label = 1 if (outcome == "TP" and net_return > min_net_return_for_positive_label) else 0
    return LabelResult(
        outcome, int(t[fill_idx]), entry_price, int(t[exit_idx]), ref_price, exit_price, net_return, label
    )
