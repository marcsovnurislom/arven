"""Trading-session calendars: when an instrument's market is open.

BTC perpetuals trade around the clock (``"24x7"``: never closed - every function below then degenerates to the
plain UTC grid, so 24x7 behaviour is byte-identical to the code that existed before calendars). Gold (XAUUSD)
follows the CME Globex metals schedule (``"cme_metals"``), defined in New York local time so that US daylight
saving is handled exactly:

- weekly: closed from Friday 17:00 to Sunday 18:00 New York time;
- daily: a one-hour halt 17:00-18:00 New York time, Monday to Thursday;
- holidays and early closes: explicit UTC windows from ``config/sessions/cme_metals_closures.csv``
  (``AppConfig.market.session_closures``).

Verified against Dukascopy XAUUSD 1m candles (zero-volume runs): Friday close 22:00 UTC in winter, Sunday open
22:00 UTC after the 2024-03-10 DST switch, daily halt 21:00-22:00 UTC in summer, Good Friday closed all day, early
closes on US holidays (see ``docs/current_state.md``, "Gold (XAUUSD)").

A minute bar ``[t, t + 1m)`` is *open* when ``t`` lies in no closed window. All windows are half-open UTC
``[start_ms, end_ms)`` on whole minutes. A higher-timeframe bucket exists (has an *expected* bar) when at least one
of its minutes is open; it is *complete* when every open minute in it has a stored 1m bar.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import cached_property
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np

from arven.core.time import UTC, to_ms
from arven.core.timeframes import Timeframe

SessionKind = Literal["24x7", "cme_metals"]
SESSION_KINDS: tuple[str, ...] = ("24x7", "cme_metals")

NEW_YORK = ZoneInfo("America/New_York")
MINUTE_MS = Timeframe.M1.ms
WEEK_MS = 7 * 86_400_000
_HALT_START, _HALT_END = time(17, 0), time(18, 0)  # CME metals daily maintenance halt, New York time


def _ny_to_ms(d: date, t: time) -> int:
    return to_ms(datetime.combine(d, t, tzinfo=NEW_YORK).astimezone(UTC))


def cme_metals_regular_closures(lo_ms: int, hi_ms: int) -> list[tuple[int, int]]:
    """Regular (non-holiday) CME metals closures overlapping ``[lo_ms, hi_ms)``, sorted, UTC ms."""
    first = datetime.fromtimestamp(lo_ms / 1000, UTC).astimezone(NEW_YORK).date() - timedelta(days=8)
    last = datetime.fromtimestamp(hi_ms / 1000, UTC).astimezone(NEW_YORK).date() + timedelta(days=8)
    out: list[tuple[int, int]] = []
    d = first
    while d <= last:
        wd = d.weekday()  # Monday = 0
        if wd == 4:  # Friday 17:00 -> Sunday 18:00
            out.append((_ny_to_ms(d, _HALT_START), _ny_to_ms(d + timedelta(days=2), _HALT_END)))
        elif wd <= 3:  # Monday-Thursday halt
            out.append((_ny_to_ms(d, _HALT_START), _ny_to_ms(d, _HALT_END)))
        d += timedelta(days=1)
    return [(s, e) for s, e in out if e > lo_ms and s < hi_ms]


def _merge(windows: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(windows):
        if e <= s:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


@dataclass(frozen=True)
class SessionCalendar:
    """When a market is open. ``extra_closures`` are holiday/early-close windows on top of the regular rule."""

    kind: SessionKind = "24x7"
    extra_closures: tuple[tuple[int, int], ...] = field(default=())

    def __post_init__(self) -> None:
        if self.kind not in SESSION_KINDS:
            raise ValueError(f"unknown session kind {self.kind!r}")
        if self.kind == "24x7" and self.extra_closures:
            raise ValueError("a 24x7 session cannot have closures")
        for s, e in self.extra_closures:
            if s % MINUTE_MS or e % MINUTE_MS or e <= s:
                raise ValueError(f"closure [{s}, {e}) must be a non-empty window on whole minutes")

    @property
    def always_open(self) -> bool:
        return self.kind == "24x7"

    # -- closed windows ----------------------------------------------------------------------------

    def closed_windows(self, lo_ms: int, hi_ms: int) -> list[tuple[int, int]]:
        """Merged closed windows overlapping ``[lo_ms, hi_ms)`` (not clipped), sorted."""
        if self.always_open:
            return []
        regular = cme_metals_regular_closures(lo_ms, hi_ms)
        extra = [(s, e) for s, e in self.extra_closures if e > lo_ms and s < hi_ms]
        return [(s, e) for s, e in _merge(regular + extra) if e > lo_ms and s < hi_ms]

    @cached_property
    def _horizon(self) -> tuple[int, int, np.ndarray, np.ndarray]:
        # One precomputed table 2015..2035 covers every use in this project; queries outside it are rebuilt.
        lo, hi = to_ms(datetime(2015, 1, 1, tzinfo=UTC)), to_ms(datetime(2035, 1, 1, tzinfo=UTC))
        w = self.closed_windows(lo, hi)
        return lo, hi, np.array([s for s, _ in w], dtype=np.int64), np.array([e for _, e in w], dtype=np.int64)

    def _tables(self, lo_ms: int, hi_ms: int) -> tuple[np.ndarray, np.ndarray]:
        h_lo, h_hi, starts, ends = self._horizon
        if lo_ms >= h_lo + WEEK_MS and hi_ms <= h_hi - WEEK_MS:
            return starts, ends
        w = self.closed_windows(lo_ms - WEEK_MS, hi_ms + WEEK_MS)
        return np.array([s for s, _ in w], dtype=np.int64), np.array([e for _, e in w], dtype=np.int64)

    # -- minutes -------------------------------------------------------------------------------------

    def is_open(self, t_ms: np.ndarray | int) -> np.ndarray | bool:
        """Whether the minute starting at ``t_ms`` (or each element of an array) is in session."""
        scalar = np.ndim(t_ms) == 0
        t = np.atleast_1d(np.asarray(t_ms, dtype=np.int64))
        if self.always_open or len(t) == 0:
            out = np.ones(len(t), dtype=bool)
        else:
            starts, ends = self._tables(int(t.min()), int(t.max()) + 1)
            idx = np.searchsorted(starts, t, side="right") - 1
            inside = (idx >= 0) & (t < ends[np.maximum(idx, 0)])
            out = ~inside
        return bool(out[0]) if scalar else out

    def open_minutes(self, lo_ms: int, hi_ms: int) -> np.ndarray:
        """Open minute opens in ``[lo_ms, hi_ms)`` (``lo_ms`` rounded up to a whole minute)."""
        first = -(-lo_ms // MINUTE_MS) * MINUTE_MS
        grid = np.arange(first, hi_ms, MINUTE_MS, dtype=np.int64)
        return grid if self.always_open else grid[self.is_open(grid)]

    # -- higher timeframes -----------------------------------------------------------------------------

    def expected_minutes(self, tf: Timeframe, bucket_opens: np.ndarray) -> np.ndarray:
        """Number of open minutes in each ``tf`` bucket starting at ``bucket_opens``."""
        b = np.asarray(bucket_opens, dtype=np.int64)
        per = tf.ms // MINUTE_MS
        if self.always_open or len(b) == 0:
            return np.full(len(b), per, dtype=np.int64)
        minutes = b[:, None] + np.arange(per, dtype=np.int64)[None, :] * MINUTE_MS
        return self.is_open(minutes.ravel()).reshape(len(b), per).sum(axis=1).astype(np.int64)

    def bar_opens(self, tf: Timeframe, lo_ms: int, hi_ms: int) -> np.ndarray:
        """Opens of the ``tf`` buckets in ``[lo_ms, hi_ms)`` (``lo_ms`` aligned up) with at least one open minute."""
        first = -(-lo_ms // tf.ms) * tf.ms
        grid = np.arange(first, hi_ms, tf.ms, dtype=np.int64)
        if self.always_open:
            return grid
        return grid[self.expected_minutes(tf, grid) > 0]

    def next_bar_open(self, tf: Timeframe, after_open_ms: int) -> int:
        """Open of the first ``tf`` bucket after the one opening at ``after_open_ms`` that has an open minute."""
        nxt = after_open_ms + tf.ms
        if self.always_open:
            return nxt
        span = 16 * 86_400_000  # longer than any closure (a holiday weekend is < 4 days)
        while True:
            opens = self.bar_opens(tf, nxt, nxt + span)
            if len(opens):
                return int(opens[0])
            nxt += span

    def next_bar_opens(self, tf: Timeframe, open_ms: np.ndarray) -> np.ndarray:
        """Vectorised :meth:`next_bar_open` for bucket opens of a sorted array."""
        o = np.asarray(open_ms, dtype=np.int64)
        if self.always_open or len(o) == 0:
            return o + tf.ms
        span = 16 * 86_400_000
        grid = self.bar_opens(tf, int(o.min()) + tf.ms, int(o.max()) + tf.ms + span)
        idx = np.searchsorted(grid, o + tf.ms, side="left")
        if np.any(idx >= len(grid)):  # pragma: no cover - span exceeds every closure
            raise RuntimeError("calendar lookahead span too short")
        return grid[idx]


def session_decision_mask(calendar: SessionCalendar | None, t: np.ndarray, tf: Timeframe = Timeframe.H1) -> np.ndarray:
    """Which decision times ``t`` (closes of ``tf`` bars) a market can act on. Around the clock: all of them. A session
    market: only those at which the market is open (an order can fill at the next minute) and whose ``tf`` bar ending
    at ``t`` was a trading bar - never inside a weekend, the daily halt or a holiday, nor at the close that starts one
    (a signal there could only be filled after the closure, at a price nobody saw)."""
    t = np.asarray(t, dtype=np.int64)
    if calendar is None or calendar.always_open:
        return np.ones(len(t), dtype=bool)
    return np.asarray(calendar.is_open(t), dtype=bool) & (calendar.expected_minutes(tf, t - tf.ms) > 0)
