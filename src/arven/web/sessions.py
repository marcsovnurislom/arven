"""The Sessions page (docs/FEATURES_PLAN.md, H2): is each market open right now, which of the world's trading centres
are in their working hours, and in which hours of the week a market has moved most.

Everything here is a pure function of a calendar, a clock and stored bars - no I/O. The market state comes from the
same :class:`~arven.core.sessions.SessionCalendar` that gates every gold signal, so the page cannot disagree with the
strategies. The four centres are context only: conventional local working hours (the usual FX-session convention), not
an exchange schedule, and they never influence a signal. The activity grid is a description of the past (the mean
range of completed 1h bars), not a forecast and not a direction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np

from arven.core.sessions import SessionCalendar
from arven.core.time import UTC, to_ms

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
HALT_MAX_MS = 2 * HOUR_MS  # a closure this short (and not a holiday) is the daily maintenance halt
LOOKAHEAD_MS = 30 * DAY_MS  # longer than any closure or open stretch of the gold session

MarketState = Literal["always_open", "open", "halt", "weekend", "holiday"]


@dataclass(frozen=True)
class Centre:
    """A trading centre on the globe: conventional local working hours, Monday to Friday."""

    id: str
    name: str
    tz: str
    lat: float
    lon: float
    open_local: time
    close_local: time


CENTRES: tuple[Centre, ...] = (
    Centre("sydney", "Sydney", "Australia/Sydney", -33.87, 151.21, time(7), time(16)),
    Centre("tokyo", "Tokyo", "Asia/Tokyo", 35.68, 139.69, time(9), time(18)),
    Centre("london", "London", "Europe/London", 51.51, -0.13, time(8), time(17)),
    Centre("new_york", "New York", "America/New_York", 40.71, -74.01, time(8), time(17)),
)


def market_state(calendar: SessionCalendar, now_ms: int, holidays: Sequence[tuple[int, int, str]] = ()) -> dict[str, Any]:
    """Whether the market is open at ``now_ms`` and when that changes.

    ``state`` is ``always_open`` (24x7), ``open``, or why it is closed: ``halt`` (the short daily pause), ``weekend``
    or ``holiday`` (the closure overlaps a holiday / early-close window of ``holidays``, whose name is ``reason``).
    ``next_change_ms`` is the reopening while closed, the next closure while open, ``None`` around the clock.
    """
    if calendar.always_open:
        return {"state": "always_open", "open": True, "next_change_ms": None, "reason": None, "closure_ends_ms": None}
    windows = calendar.closed_windows(now_ms - LOOKAHEAD_MS, now_ms + LOOKAHEAD_MS)
    for s, e in windows:
        if s <= now_ms < e:
            names = [r for hs, he, r in holidays if he > s and hs < e]
            state: MarketState = "holiday" if names else ("halt" if e - s <= HALT_MAX_MS else "weekend")
            return {"state": state, "open": False, "next_change_ms": e, "reason": names[0] if names else None, "closure_ends_ms": e}
    nxt = next(((s, e) for s, e in windows if s > now_ms), None)
    return {"state": "open", "open": True, "next_change_ms": None if nxt is None else nxt[0], "reason": None,
            "closure_ends_ms": None if nxt is None else nxt[1]}


def next_holiday(holidays: Sequence[tuple[int, int, str]], now_ms: int) -> dict[str, Any] | None:
    """The first holiday / early-close window that has not ended yet."""
    upcoming = sorted((s, e, r) for s, e, r in holidays if e > now_ms)
    if not upcoming:
        return None
    s, e, r = upcoming[0]
    return {"start_ms": s, "end_ms": e, "reason": r}


def centre_status(c: Centre, now_ms: int) -> dict[str, Any]:
    """Whether ``c`` is inside its local working hours at ``now_ms`` and the UTC ms of the next open/close (DST-exact)."""
    tz = ZoneInfo(c.tz)
    today = datetime.fromtimestamp(now_ms / 1000, UTC).astimezone(tz).date()
    windows = []
    for k in range(-1, 9):
        d = today + timedelta(days=k)
        if d.weekday() < 5:
            windows.append((to_ms(datetime.combine(d, c.open_local, tzinfo=tz)), to_ms(datetime.combine(d, c.close_local, tzinfo=tz))))
    current = next(((s, e) for s, e in windows if s <= now_ms < e), None)
    if current is not None:
        is_open, change = True, current[1]
    else:
        is_open, change = False, next(s for s, _ in windows if s > now_ms)
    return {"id": c.id, "name": c.name, "tz": c.tz, "lat": c.lat, "lon": c.lon, "open_local": c.open_local.strftime("%H:%M"),
            "close_local": c.close_local.strftime("%H:%M"), "open": is_open, "next_change_ms": change}


def activity_grid(open_time_ms: np.ndarray, open_: np.ndarray, high: np.ndarray, low: np.ndarray, close_time_ms: np.ndarray,
                  now_ms: int) -> dict[str, Any]:
    """Mean range ``(high - low) / open`` in percent of 1h bars per UTC weekday (Monday = 0) and hour.

    Only bars that have closed by ``now_ms`` count (no partial bar); a cell without bars is ``None`` (a closed market,
    not a quiet one). ``n`` is the number of bars behind each cell.
    """
    t = np.asarray(open_time_ms, dtype=np.int64)
    o, h, lo = (np.asarray(x, dtype=float) for x in (open_, high, low))
    ok = (np.asarray(close_time_ms, dtype=np.int64) < now_ms) & np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & (o > 0)
    t, rng = t[ok], (h[ok] - lo[ok]) / o[ok] * 100.0
    # 1970-01-01 was a Thursday (weekday 3)
    slot = ((t // DAY_MS + 3) % 7) * 24 + (t % DAY_MS) // HOUR_MS
    n = np.bincount(slot, minlength=168)
    total = np.bincount(slot, weights=rng, minlength=168)
    mean = [None if n[k] == 0 else round(float(total[k] / n[k]), 4) for k in range(168)]
    return {
        "mean_range_pct": [mean[d * 24:(d + 1) * 24] for d in range(7)],
        "n": [[int(x) for x in n[d * 24:(d + 1) * 24]] for d in range(7)],
        "bars": int(len(t)),
        "from_ms": int(t.min()) if len(t) else None,
        "to_ms": int(t.max()) + HOUR_MS if len(t) else None,
    }


__all__ = ["CENTRES", "Centre", "activity_grid", "centre_status", "market_state", "next_holiday"]
