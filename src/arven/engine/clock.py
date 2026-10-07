"""The event-driven analogue of ``arven.backtest.clock.Clock`` (kept unchanged, legacy 1h-only path):
instead of advancing through a flat grid of same-timeframe timestamps, ``EventClock`` advances through
:class:`~arven.engine.events.BarCloseEvent`, one per timeframe's bar close, merged across however many
timeframes a symbol's strategies care about.

**Tie rule (fixed, documented, deterministic):** events sharing the same ``close_ms`` are ordered from the
COARSEST timeframe to the FINEST. A 4h close always coincides with a 1h/15m/5m/1m close; this rule
guarantees that by the time a strategy's own (finer) ``trigger_tf`` event is emitted at that instant, any
coarser-or-equal timeframe's same-instant close - typically its own ``context_tfs``/``setup_tf`` - has
already been emitted as closed. This removes a whole class of same-instant look-ahead bugs by construction
(event order itself), rather than relying solely on ``available_at`` arithmetic downstream.
"""

from __future__ import annotations

from typing import Protocol

from arven.core.time import from_ms, to_ms
from arven.core.timeframes import Timeframe, iter_bar_opens
from arven.engine.events import BarCloseEvent


class EventClock(Protocol):
    @property
    def now_ms(self) -> int: ...

    def advance(self) -> BarCloseEvent | None:
        """Move to the next event (by the tie rule above) and return it, or ``None`` when exhausted."""
        ...


class SimulatedEventClock:
    """Builds the full ordered event sequence once, up front, from the configured timeframes over
    ``[start_ms, end_ms)`` - the same precomputed-grid determinism approach ``SimulationClock`` already
    uses for the legacy path. Single-symbol (multi-symbol generalisation is a later, explicitly separate
    phase per the master prompt)."""

    def __init__(
        self, symbol: str, timeframes: tuple[Timeframe, ...], start_ms: int, end_ms: int, delay_ms: int = 0,
    ) -> None:
        if not symbol:
            raise ValueError("symbol must not be empty")
        if not timeframes:
            raise ValueError("at least one timeframe is required")
        if len(set(timeframes)) != len(timeframes):
            raise ValueError("timeframes must not repeat")
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        if end_ms <= start_ms:
            raise ValueError("end_ms must be after start_ms")

        events: list[BarCloseEvent] = []
        for tf in timeframes:
            for open_dt in iter_bar_opens(from_ms(start_ms), from_ms(end_ms), tf):
                open_ms = to_ms(open_dt)
                close_ms = open_ms + tf.ms
                events.append(BarCloseEvent(symbol, tf, open_ms, close_ms, close_ms + delay_ms))
        events.sort(key=lambda e: (e.close_ms, -e.timeframe.ms))  # coarsest-first within equal close_ms
        self._events: tuple[BarCloseEvent, ...] = tuple(events)
        self._i = -1

    @property
    def events(self) -> tuple[BarCloseEvent, ...]:
        """The full precomputed sequence (read-only; for tests and tooling, not consumed by the loop)."""
        return self._events

    @property
    def now_ms(self) -> int:
        if self._i < 0:
            raise RuntimeError("clock has not started")
        return self._events[self._i].close_ms

    @property
    def started(self) -> bool:
        return self._i >= 0

    def advance(self) -> BarCloseEvent | None:
        if self._i + 1 >= len(self._events):
            return None
        self._i += 1
        return self._events[self._i]
