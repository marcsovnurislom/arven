"""The event the new engine schedules on: one timeframe's bar closing for one symbol."""

from __future__ import annotations

from dataclasses import dataclass

from arven.core.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class BarCloseEvent:
    """``close_ms`` is both the bar's close time and the decision/event time. ``available_at_ms`` is
    ``close_ms`` plus whatever availability delay the caller configured (mirrors
    ``core.timeframes.bar_available_at`` exactly - never computed differently here)."""

    symbol: str
    timeframe: Timeframe
    open_ms: int
    close_ms: int
    available_at_ms: int

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.close_ms != self.open_ms + self.timeframe.ms:
            raise ValueError("close_ms must equal open_ms + timeframe duration")
        if self.available_at_ms < self.close_ms:
            raise ValueError("available_at_ms must not be earlier than close_ms")
