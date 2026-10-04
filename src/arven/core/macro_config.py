"""Macro event calendar (Stage 9a): FOMC / CPI / NFP release schedule, used only for the risk engine's
event-blackout rule (architecture.md section 14, rule 2). No actual released values are stored or used -
only the *scheduled* time, which is public knowledge announced months to a year in advance, so using it at
any decision time carries no look-ahead risk (unlike the eventual released number, which Stage 9b's news/
LLM work would need to treat with the usual available_at discipline - out of scope here).

``config/macro_events.csv`` columns: ``date`` (UTC calendar date), ``event_type`` (FOMC|CPI|NFP), ``time_et``
(the release's clock time in US Eastern local time), ``note`` (free text, e.g. a shutdown-driven reschedule;
never parsed).

ET->UTC is computed directly from the fixed US DST rule (2nd Sunday of March to 1st Sunday of November,
unchanged since the Energy Policy Act of 2005 took effect in 2007 - every date in this calendar falls after
that) rather than via ``zoneinfo``: this machine's Python has no system IANA tz database installed (Windows
ships none by default), and the `tzdata` PyPI package is a new dependency this project avoids unless
necessary - a fixed, two-rule legal calendar is cheap and correct to compute directly instead.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.time import UTC, to_ms

MACRO_EVENTS_FILE = "macro_events.csv"
US_EASTERN_STANDARD_OFFSET_HOURS = -5  # EST
US_EASTERN_DAYLIGHT_OFFSET_HOURS = -4  # EDT


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)  # date.weekday(): Mon=0 .. Sun=6
    return first_sunday + timedelta(days=7 * (n - 1))


def us_eastern_utc_offset_hours(d: date) -> int:
    """US Eastern's UTC offset on calendar date ``d``: DST from the 2nd Sunday of March to the 1st Sunday of
    November (exclusive), EST otherwise. Valid for any date from 2007 onward (every row in this calendar
    is)."""
    dst_start = _nth_sunday(d.year, 3, 2)
    dst_end = _nth_sunday(d.year, 11, 1)
    return US_EASTERN_DAYLIGHT_OFFSET_HOURS if dst_start <= d < dst_end else US_EASTERN_STANDARD_OFFSET_HOURS


@dataclass(frozen=True, slots=True)
class MacroEvent:
    scheduled_at_ms: int
    event_type: str
    note: str


def load_macro_events(config_dir: Path | str | None = None) -> tuple[MacroEvent, ...]:
    """Parse ``macro_events.csv`` into UTC-ms-stamped, time-sorted events."""
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    path = config_dir / MACRO_EVENTS_FILE
    events: list[MacroEvent] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            date_part = datetime.strptime(row["date"], "%Y-%m-%d").date()
            hour, minute = (int(x) for x in row["time_et"].split(":"))
            local_naive = datetime(date_part.year, date_part.month, date_part.day, hour, minute)
            utc_naive = local_naive - timedelta(hours=us_eastern_utc_offset_hours(date_part))
            events.append(MacroEvent(to_ms(utc_naive.replace(tzinfo=UTC)), row["event_type"], row.get("note") or ""))
    events.sort(key=lambda e: e.scheduled_at_ms)
    return tuple(events)


def macro_events_hash(events: tuple[MacroEvent, ...]) -> str:
    """Content hash of the loaded calendar (independent of file formatting) - recorded in run manifests the
    same way other config/data inputs are, for provenance."""
    h = hashlib.sha256()
    for e in events:
        h.update(f"{e.scheduled_at_ms}|{e.event_type}|{e.note}\n".encode())
    return h.hexdigest()
