"""How markets moved after past macro events (docs/FEATURES_PLAN.md, H1): the news countdown's history.

For every scheduled FOMC / CPI / NFP release (``config/macro_events.csv``) and each horizon (15 min, 1 h, 4 h after the
release) this measures, on stored 15m bars:

- ``range``: (highest high - lowest low) / the price at the release, in percent - how far the price travelled;
- ``move``: |close at the end of the horizon - price at the release| / that price, in percent - where it ended up,
  without the direction;
- ``baseline``: the median ``range`` of the same UTC clock window on up to ``BASELINE_DAYS`` earlier weekdays with no
  event at all - an ordinary day at that hour, to compare with.

On a session market (gold) a horizon is counted in trading time: "1 h after" is the first four 15m bars the market
was open, so the daily one-hour pause is skipped, but a window that would need more than ``MAX_PAUSE_MS`` of closure
(a weekend, a holiday) is left out. It describes size, never direction, and it is history, not a forecast. Leakage:
an event counts only when its whole window has closed (its last bar closed by ``now``), and its baseline uses earlier
days only. A window with a missing bar (a data gap) is left out rather than filled. Pure functions over arrays, plus
one loader for the stored bars (:func:`load_bars`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import duckdb
import numpy as np

from arven.core.macro_config import MacroEvent
from arven.core.sessions import SessionCalendar
from arven.core.timeframes import Timeframe

M15 = 15 * 60_000
DAY_MS = 86_400_000
HORIZONS_MIN: tuple[int, ...] = (15, 60, 240)
BASELINE_DAYS = 20  # earlier event-free weekdays averaged into the "ordinary day" at the same hour
BASELINE_MIN_DAYS = 5  # fewer usable days than this -> no baseline
BASELINE_LOOKBACK_DAYS = 45  # how far back to search for them
MAX_PAUSE_MS = 2 * 3_600_000  # closed time a trading-time window may skip (the daily halt), not a weekend

EVENT_TYPES: tuple[str, ...] = ("FOMC", "CPI", "NFP")


@dataclass(frozen=True)
class Bars:
    """15m bars of one market, ascending by open time (several feeds merged: the first one wins on a duplicate)."""

    open_time_ms: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @staticmethod
    def empty() -> Bars:
        z = np.array([], dtype=float)
        return Bars(np.array([], dtype=np.int64), z, z, z, z)


def load_bars(con: duckdb.DuckDBPyConnection, symbols: Sequence[str]) -> Bars:
    """Complete stored 15m bars of ``symbols`` (e.g. gold's live feed, then its history), merged by open time."""
    parts: list[tuple] = []
    seen: set[int] = set()
    for symbol in symbols:
        for row in con.execute(
            "SELECT open_time_ms, open, high, low, close FROM ohlcv WHERE symbol = ? AND timeframe = '15m' AND is_complete ORDER BY open_time_ms",
            [symbol],
        ).fetchall():
            if row[0] not in seen:
                seen.add(row[0])
                parts.append(row)
    if not parts:
        return Bars.empty()
    parts.sort(key=lambda r: r[0])
    t, o, h, lo, c = (np.asarray(x) for x in zip(*parts, strict=True))
    return Bars(t.astype(np.int64), o.astype(float), h.astype(float), lo.astype(float), c.astype(float))


def expected_opens(start_ms: int, minutes: int, calendar: SessionCalendar | None) -> np.ndarray | None:
    """The 15m bar opens making up ``minutes`` of trading from ``start_ms`` (the market must be open at ``start_ms``);
    ``None`` when that needs more than ``MAX_PAUSE_MS`` of closure."""
    n = minutes * 60_000 // M15
    if calendar is None or calendar.always_open:
        return start_ms + M15 * np.arange(n, dtype=np.int64)
    opens = calendar.bar_opens(Timeframe.M15, start_ms, start_ms + minutes * 60_000 + MAX_PAUSE_MS)[:n]
    if len(opens) < n or opens[0] != start_ms:
        return None
    return opens


def window(bars: Bars, start_ms: int, minutes: int, now_ms: int, calendar: SessionCalendar | None = None) -> tuple[float, float] | None:
    """``(range %, move %)`` of the ``minutes`` of trading after ``start_ms``, or ``None`` when the window is not fully
    closed by ``now_ms``, crosses a long closure, or any of its 15m bars is missing."""
    if start_ms % M15:
        return None
    want = expected_opens(start_ms, minutes, calendar)
    if want is None or int(want[-1]) + M15 > now_ms:
        return None
    n = len(want)
    i = int(np.searchsorted(bars.open_time_ms, start_ms))
    if i + n > len(bars.open_time_ms) or not np.array_equal(bars.open_time_ms[i:i + n], want):
        return None
    p0 = bars.open[i]
    if not p0 > 0:
        return None
    hi, lo = float(bars.high[i:i + n].max()), float(bars.low[i:i + n].min())
    return (hi - lo) / p0 * 100.0, abs(float(bars.close[i + n - 1]) - p0) / p0 * 100.0


def baseline(bars: Bars, start_ms: int, minutes: int, event_days: set[int], now_ms: int, calendar: SessionCalendar | None = None) -> float | None:
    """Median range of the same UTC window on up to ``BASELINE_DAYS`` earlier weekdays without any event."""
    ranges: list[float] = []
    for k in range(1, BASELINE_LOOKBACK_DAYS + 1):
        s = start_ms - k * DAY_MS
        day = s // DAY_MS
        if (day + 3) % 7 >= 5 or day in event_days:  # 1970-01-01 was a Thursday: (day + 3) % 7 is Monday = 0
            continue
        w = window(bars, s, minutes, now_ms, calendar)
        if w is not None:
            ranges.append(w[0])
            if len(ranges) == BASELINE_DAYS:
                break
    return float(np.median(ranges)) if len(ranges) >= BASELINE_MIN_DAYS else None


def event_rows(bars: Bars, events: Sequence[MacroEvent], now_ms: int, horizons: Sequence[int] = HORIZONS_MIN,
               calendar: SessionCalendar | None = None) -> list[dict[str, Any]]:
    """One row per past event with at least one measurable horizon: its time, type and per-horizon numbers."""
    event_days = {e.scheduled_at_ms // DAY_MS for e in events}
    out = []
    for e in events:
        per: dict[str, Any] = {}
        for h in horizons:
            w = window(bars, e.scheduled_at_ms, h, now_ms, calendar)
            if w is None:
                continue
            per[str(h)] = {"range": round(w[0], 4), "move": round(w[1], 4),
                           "baseline": _r(baseline(bars, e.scheduled_at_ms, h, event_days, now_ms, calendar))}
        if per:
            out.append({"time_ms": e.scheduled_at_ms, "type": e.event_type, "note": e.note, "horizons": per})
    return out


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def summarize(rows: Sequence[dict[str, Any]], horizons: Sequence[int] = HORIZONS_MIN) -> dict[str, dict[str, Any]]:
    """Per event type and horizon: how many events, median / mean / largest range, median move, the ordinary-day
    baseline and how often the event hour moved more than an ordinary one."""
    out: dict[str, dict[str, Any]] = {}
    for typ in EVENT_TYPES:
        per: dict[str, Any] = {}
        for h in horizons:
            got = [r for r in rows if r["type"] == typ and str(h) in r["horizons"]]
            if not got:
                per[str(h)] = {"n": 0}
                continue
            rng = np.array([r["horizons"][str(h)]["range"] for r in got])
            mv = np.array([r["horizons"][str(h)]["move"] for r in got])
            pairs = [(r["horizons"][str(h)]["range"], r["horizons"][str(h)]["baseline"]) for r in got if r["horizons"][str(h)]["baseline"]]
            worst = got[int(rng.argmax())]
            per[str(h)] = {
                "n": len(got), "median_range": _r(float(np.median(rng))), "mean_range": _r(float(rng.mean())),
                "max_range": _r(float(rng.max())), "max_time_ms": worst["time_ms"], "median_move": _r(float(np.median(mv))),
                "median_baseline": _r(float(np.median([b for _, b in pairs]))) if pairs else None,
                "median_ratio": _r(float(np.median([a / b for a, b in pairs]))) if pairs else None,
                "share_above_baseline": _r(float(np.mean([a > b for a, b in pairs]))) if pairs else None,
                "n_baseline": len(pairs),
            }
        out[typ] = per
    return out


def upcoming(events: Sequence[MacroEvent], now_ms: int, limit: int = 6) -> list[dict[str, Any]]:
    return [{"time_ms": e.scheduled_at_ms, "type": e.event_type, "note": e.note} for e in events if e.scheduled_at_ms > now_ms][:limit]


def calendar_known_until(events: Sequence[MacroEvent]) -> dict[str, int | None]:
    """The last scheduled release of each type in the calendar - beyond it the countdown simply has nothing."""
    return {t: max((e.scheduled_at_ms for e in events if e.event_type == t), default=None) for t in EVENT_TYPES}


def due_reminders(events: Sequence[MacroEvent], now_ms: int, lead_minutes: int) -> list[MacroEvent]:
    """Events whose reminder time (``lead_minutes`` before) has come and that have not started yet."""
    lead = lead_minutes * 60_000
    return [e for e in events if e.scheduled_at_ms - lead <= now_ms < e.scheduled_at_ms]


__all__ = ["BASELINE_DAYS", "Bars", "EVENT_TYPES", "HORIZONS_MIN", "baseline", "calendar_known_until", "due_reminders",
           "event_rows", "expected_opens", "load_bars", "summarize", "upcoming", "window"]
