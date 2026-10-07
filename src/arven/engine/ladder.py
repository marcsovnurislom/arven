"""Pure R-multiple math for a (possibly partial) TP-ladder exit. Deliberately separate from
``paper_tracker`` (which walks 1m bars and knows about fees/slippage *models*): this module only sums
already-resolved legs - exactly the kind of small, pure function CLAUDE.md asks to have hand-computed
test cases, not a model to trust by construction.

Convention, chosen to match the existing single-exit convention exactly
(``arven.backtest.accounting``'s ``risk = qty * abs(entry_price - stop_price)``,
``r_multiple = net_pnl / risk``): everything here is expressed **per unit of the original position size**
(so the ladder's blended R does not depend on how large the position actually was), and risk is the
absolute entry-to-stop price distance, never ``stop_pct``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClosedLeg:
    """One already-resolved piece of the position (a TP rung, a stop, a time stop) - prices are the
    actual fill (post-slippage), not the planned level."""

    fraction: float  # of the original size, in (0, 1]
    exit_price: float
    fee: float  # $ paid, per unit of original size, >= 0
    exit_reason: str  # free text ("TP1", "STOP", "TIME_STOP", ...): not interpreted here

    def __post_init__(self) -> None:
        if not (math.isfinite(self.fraction) and 0 < self.fraction <= 1):
            raise ValueError("fraction must be in (0, 1]")
        if not (math.isfinite(self.exit_price) and self.exit_price > 0):
            raise ValueError("exit_price must be finite and positive")
        if not (math.isfinite(self.fee) and self.fee >= 0):
            raise ValueError("fee must be finite and non-negative")
        if not self.exit_reason:
            raise ValueError("exit_reason must not be empty")


@dataclass(frozen=True, eq=False)
class LadderResolution:
    legs: tuple[ClosedLeg, ...]
    gross_pnl: float  # per unit of original size
    fees: float
    net_pnl: float
    r_multiple: float
    fully_closed: bool  # legs' fractions sum to ~1.0 (nothing of the original size remains open)


def resolve_legs(entry_price: float, stop_price: float, side: int, legs: Sequence[ClosedLeg]) -> LadderResolution:
    """Blend however many legs already closed into one net-of-fees R-multiple.

    Gross pnl of one leg (per unit of original size) is ``fraction * side * (exit_price - entry_price)`` -
    by construction this equals ``fraction * r_multiple`` when ``exit_price`` is exactly a planned
    :class:`~arven.engine.signal.TPLevel` price, so a ladder that fills every rung exactly at its planned
    level blends to ``sum(fraction_i * r_multiple_i)`` before fees, matching simple intuition.
    """
    if side not in (1, -1):
        raise ValueError("side must be +1 or -1")
    if not (math.isfinite(entry_price) and entry_price > 0):
        raise ValueError("entry_price must be finite and positive")
    risk = abs(entry_price - stop_price)
    if not (math.isfinite(risk) and risk > 0):
        raise ValueError("entry_price and stop_price must be finite and distinct")
    if not legs:
        raise ValueError("at least one closed leg is required")
    total_fraction = sum(leg.fraction for leg in legs)
    if total_fraction > 1.0 + 1e-9:
        raise ValueError(f"leg fractions must not sum to more than 1.0, got {total_fraction}")
    gross = sum(leg.fraction * side * (leg.exit_price - entry_price) for leg in legs)
    fees = sum(leg.fee for leg in legs)
    net = gross - fees
    return LadderResolution(
        legs=tuple(legs), gross_pnl=gross, fees=fees, net_pnl=net, r_multiple=net / risk,
        fully_closed=abs(total_fraction - 1.0) < 1e-9,
    )
