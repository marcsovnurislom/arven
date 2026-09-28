"""The trade signal contract.

The decision / risk stack (Stage 5) will produce :class:`Signal` objects; the backtester (and later the
live loop) consumes them. It lives in ``core`` so that neither side has to import the other.

A signal is a request made at decision time ``t_ms`` (a 1h bar close) using only information available then.
Sizes and distances are expressed relative to quantities that are unknown at decision time (equity at
fill, fill price), so nothing here can smuggle in future prices.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arven.core.types import Action


@dataclass(frozen=True, slots=True)
class Signal:
    t_ms: int
    action: Action
    # Target notional as a fraction of equity at the decision (LONG / SHORT only).
    notional_fraction: float | None = None
    # Stop / take-profit distance as a fraction of the fill price (optional).
    stop_pct: float | None = None
    take_profit_pct: float | None = None
    # Exit at the open of the first 1m bar at or after entry + this many minutes (optional).
    max_holding_minutes: int | None = None
    # NO_TRADE + close_position: ask to close the open position (ignored when flat).
    close_position: bool = False
    # Opaque label carried into the logs; never interpreted.
    tag: str = ""

    def __post_init__(self) -> None:
        if self.action in (Action.LONG, Action.SHORT):
            if self.notional_fraction is None or not (math.isfinite(self.notional_fraction) and self.notional_fraction > 0):
                raise ValueError("LONG/SHORT signals need a finite notional_fraction > 0")
            if self.close_position:
                raise ValueError("close_position is only valid with NO_TRADE")
        else:
            if self.notional_fraction is not None or self.stop_pct is not None or self.take_profit_pct is not None:
                raise ValueError("NO_TRADE signals carry no sizing or barriers")
        if self.stop_pct is not None and not (math.isfinite(self.stop_pct) and 0 < self.stop_pct < 1):
            raise ValueError("stop_pct must be in (0, 1)")
        if self.take_profit_pct is not None and not (math.isfinite(self.take_profit_pct) and self.take_profit_pct > 0):
            raise ValueError("take_profit_pct must be > 0")
        if self.max_holding_minutes is not None and self.max_holding_minutes < 1:
            raise ValueError("max_holding_minutes must be >= 1")
