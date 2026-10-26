"""Timeframes and bar-time arithmetic.

Conventions (used everywhere in ARVEN):

- A bar covers the half-open interval ``[open_time, close_time)``.
- ``close_time = open_time + duration``. (Binance reports ``close_time`` as ``open_time + duration - 1ms``;
  adapters normalise that to this convention.)
- Bars are aligned to the UTC epoch. For all supported timeframes (<= 1d) this matches exchange
  alignment, since each divides a UTC day (1d bars open at 00:00 UTC; 30m and 1d added 2026-10-27).
- A bar's information becomes usable only at ``available_at = close_time + delay``. Nothing about a bar
  may be used at any time earlier than that.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from enum import StrEnum

from arven.core.time import ensure_utc, from_ms, to_ms


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def duration(self) -> timedelta:
        return _DURATIONS[self]

    @property
    def ms(self) -> int:
        return self.duration // timedelta(milliseconds=1)


_DURATIONS: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.M30: timedelta(minutes=30),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
}


def is_aligned(ts: datetime, tf: Timeframe) -> bool:
    """True if ``ts`` lies exactly on a bar boundary of ``tf``."""
    return to_ms(ts) % tf.ms == 0 and ensure_utc(ts).microsecond % 1000 == 0


def floor_to_bar(ts: datetime, tf: Timeframe) -> datetime:
    """Open time of the bar that contains ``ts``."""
    ms = to_ms(ts)
    return from_ms(ms - ms % tf.ms)


def ceil_to_bar(ts: datetime, tf: Timeframe) -> datetime:
    """Smallest bar boundary ``>= ts``."""
    floored = floor_to_bar(ts, tf)
    return floored if floored == ensure_utc(ts) else floored + tf.duration


def bar_close_time(open_time: datetime, tf: Timeframe) -> datetime:
    """Close time of the bar opening at ``open_time`` (which must be aligned)."""
    if not is_aligned(open_time, tf):
        raise ValueError(f"{open_time.isoformat()} is not aligned to {tf}")
    return ensure_utc(open_time) + tf.duration


def bar_available_at(open_time: datetime, tf: Timeframe, delay: timedelta = timedelta(0)) -> datetime:
    """Earliest time at which the bar opening at ``open_time`` may be used."""
    if delay < timedelta(0):
        raise ValueError("availability delay must be non-negative")
    return bar_close_time(open_time, tf) + delay


def last_closed_bar_open(t: datetime, tf: Timeframe, delay: timedelta = timedelta(0)) -> datetime:
    """Open time of the most recent ``tf`` bar that is available at time ``t``.

    With zero delay: at exactly 12:00 the 11:00–12:00 1h bar is available; at 12:30 it is still the
    latest one (the 12:00–13:00 bar is incomplete).
    """
    if delay < timedelta(0):
        raise ValueError("availability delay must be non-negative")
    return floor_to_bar(ensure_utc(t) - delay, tf) - tf.duration


def iter_bar_opens(start: datetime, end: datetime, tf: Timeframe) -> Iterator[datetime]:
    """Aligned bar open times in ``[start, end)``."""
    current = ceil_to_bar(start, tf)
    end = ensure_utc(end)
    while current < end:
        yield current
        current += tf.duration


def iter_bar_closes(start: datetime, end: datetime, tf: Timeframe) -> Iterator[datetime]:
    """Bar close times (= decision times) in ``[start, end)``.

    Close times coincide with bar boundaries, so this is the same grid as :func:`iter_bar_opens`;
    the separate name documents intent at call sites (the decision clock).
    """
    return iter_bar_opens(start, end, tf)
