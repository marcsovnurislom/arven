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

from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from arven.core.time import from_ms, to_ms, utc_now
from arven.core.timeframes import Timeframe, floor_to_bar, iter_bar_opens
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


class LiveEventClock:
    """The live counterpart of :class:`SimulatedEventClock` (`docs/ARVEN_MASTER_PROMPT.md` section 5.1's
    "a live implementation (bar confirmed closed + derived TF bars complete)") - advances by comparing a
    real wall-clock reading to each timeframe's own next-due close, instead of walking a precomputed grid.

    **Restart-safe by construction, not by a separate persisted cursor**: the constructor takes
    ``start_after_ms``, the last close time already processed (e.g. read back from wherever the caller
    already durably recorded its own progress - a paper run's own index, a heartbeat file, ...); every
    timeframe resumes independently from the boundary at-or-before that instant, so a restart replays
    nothing already processed and skips nothing in between (one ``advance()`` call drains every bar a
    timeframe missed while the process was down, oldest first, before moving to the next timeframe - the
    same "catch up on every bar missed while the process was down" requirement of section 5.2).

    One wall-clock read per ``advance()`` call (via the injectable ``now_fn``, mirroring this project's
    existing injectable-time-source pattern, e.g. ``paper.runs.run_paper_tick``'s own ``now`` parameter) -
    never read anywhere else, so a test can fully control what time this clock believes it is.
    """

    def __init__(
        self,
        symbol: str,
        timeframes: tuple[Timeframe, ...],
        start_after_ms: int,
        delay_ms: int = 0,
        now_fn: Callable[[], datetime] = utc_now,
    ) -> None:
        if not symbol:
            raise ValueError("symbol must not be empty")
        if not timeframes:
            raise ValueError("at least one timeframe is required")
        if len(set(timeframes)) != len(timeframes):
            raise ValueError("timeframes must not repeat")
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative")
        self._symbol = symbol
        self._timeframes = timeframes
        self._delay_ms = delay_ms
        self._now_fn = now_fn
        self._last_close_ms: dict[Timeframe, int] = {
            tf: to_ms(floor_to_bar(from_ms(start_after_ms), tf)) for tf in timeframes
        }
        self._pending: deque[BarCloseEvent] = deque()
        self._last_returned_close_ms: int | None = None

    @property
    def now_ms(self) -> int:
        if self._last_returned_close_ms is None:
            raise RuntimeError("clock has not started")
        return self._last_returned_close_ms

    @property
    def started(self) -> bool:
        return self._last_returned_close_ms is not None

    def advance(self) -> BarCloseEvent | None:
        if not self._pending:
            now_ms = to_ms(self._now_fn())
            fresh: list[BarCloseEvent] = []
            for tf in self._timeframes:
                next_close = self._last_close_ms[tf] + tf.ms
                while next_close + self._delay_ms <= now_ms:
                    fresh.append(BarCloseEvent(self._symbol, tf, next_close - tf.ms, next_close, next_close + self._delay_ms))
                    self._last_close_ms[tf] = next_close
                    next_close += tf.ms
            fresh.sort(key=lambda e: (e.close_ms, -e.timeframe.ms))  # coarsest-first within equal close_ms
            self._pending.extend(fresh)
        if not self._pending:
            return None
        event = self._pending.popleft()
        self._last_returned_close_ms = event.close_ms
        return event
