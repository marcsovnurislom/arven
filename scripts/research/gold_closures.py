"""Derive ``config/sessions/cme_metals_closures.csv`` (gold's holiday closures and early closes) from the Dukascopy
XAUUSD feed, and project the coming holidays. Research tooling: it prints the CSV; the file is written only with
``--write``.

1. Evidence: runs of at least 30 consecutive zero-volume minutes inside *regular* CME metals hours (the closed market;
   ``arven.data.dukascopy_ingestion.zero_volume_runs``), merged across midnight.
2. A run starting one minute before a quarter hour (18:29, 21:59 - the last quoted minute before the halt is flat) is
   snapped to the quarter hour.
3. Every run is matched to a US exchange holiday (New Year, MLK, Presidents, Good Friday, Memorial, Juneteenth from 2022,
   Independence, Labor, Thanksgiving and the day after, Christmas Eve / Day, New Year's Eve; observed dates when they
   fall on a weekend). An unmatched run is printed as ``UNMATCHED`` and left out - it is a feed gap, not a closure.
4. Future holidays (after the last downloaded day, through 2027) get the closure pattern of that holiday's most recent
   observed year, in Chicago time (CME's own clock), so the live gold signals also stop on holidays.

Usage: PYTHONPATH=src python scripts/research/gold_closures.py [--write]
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from arven.core.config import DEFAULT_CONFIG_DIR, SESSIONS_DIR, load_config
from arven.core.sessions import SessionCalendar
from arven.core.time import UTC, from_ms, to_ms
from arven.data.adapters.dukascopy import DukaDayFile, decode_m1, mid_candles, plan_days
from arven.data.dukascopy_ingestion import zero_volume_runs

CHICAGO = ZoneInfo("America/Chicago")
MIN_MINUTES = 30
LAST_YEAR = 2027
HEADER = """# Holiday closures and early closes of CME Globex metals (gold) on top of the regular rule in arven.core.sessions.
# UTC, half-open [start_utc, end_utc), whole minutes. History rows are derived from Dukascopy XAUUSD zero-volume
# runs inside regular hours (scripts/research/gold_closures.py); future rows repeat each holiday's latest observed
# pattern in Chicago time ("projected").
start_utc,end_utc,reason,source
"""


def _nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y: int, m: int, weekday: int) -> date:
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    return date(y, month, (h + l_ - 7 * m + 114) % 31 + 1)


def _observed(d: date) -> date:
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def us_holidays(y: int) -> dict[date, str]:
    h = {
        _observed(date(y, 1, 1)): "New Year's Day",
        _nth_weekday(y, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(y, 2, 0, 3): "Presidents' Day",
        _easter(y) - timedelta(days=2): "Good Friday",
        _last_weekday(y, 5, 0): "Memorial Day",
        _observed(date(y, 7, 4)): "Independence Day",
        _nth_weekday(y, 9, 0, 1): "Labor Day",
        _nth_weekday(y, 11, 3, 4): "Thanksgiving",
        _nth_weekday(y, 11, 3, 4) + timedelta(days=1): "Day after Thanksgiving",
        _observed(date(y, 12, 25)): "Christmas",
    }
    # the eves never displace an observed holiday on the same date (Christmas on a Saturday is observed on the 24th)
    h.setdefault(date(y, 12, 24), "Christmas Eve")
    h.setdefault(date(y, 12, 31), "New Year's Eve")
    if y >= 2022:
        h[_observed(date(y, 6, 19))] = "Juneteenth"
    return h


def holiday_of(t_ms: int, span_ms: int) -> tuple[date, str] | None:
    """The holiday a closure belongs to: the New York date of the closure's middle, else the day after (an evening
    early close before a holiday, e.g. Christmas Eve), else the day before. Weekend dates are skipped: a Friday-to-
    Monday closure belongs to the Monday holiday, not to an eve that fell on the Sunday (its pattern, projected onto a
    weekday eve, would close ordinary trading days)."""
    d = from_ms(t_ms + span_ms // 2).astimezone(ZoneInfo("America/New_York")).date()
    for cand in (d, d + timedelta(days=1), d - timedelta(days=1)):
        name = us_holidays(cand.year).get(cand)
        if name and cand.weekday() < 5:
            return cand, name
    return None


def observed_runs(cfg) -> tuple[list[tuple[int, int]], date]:
    regular = SessionCalendar(cfg.market.session)
    runs: list[tuple[int, int]] = []
    last_day = None
    for day in plan_days(cfg.dukascopy.instrument, cfg.data.history_start, datetime.now(UTC)):
        paths = [cfg.data.raw_dir / DukaDayFile(cfg.dukascopy.instrument, day, s).key for s in ("BID", "ASK")]
        if not all(p.exists() for p in paths):
            continue
        last_day = day
        mid = mid_candles(*(decode_m1(p.read_bytes(), day, cfg.dukascopy.point) for p in paths))
        is_open = regular.is_open(mid.time_ms) if len(mid) else np.zeros(0, dtype=bool)
        for s, e in zero_volume_runs(mid, 1):
            sel = (mid.time_ms >= s) & (mid.time_ms < e) & is_open
            if not sel.any():
                continue
            o = mid.time_ms[sel]
            run = (int(o[0]), int(o[-1]) + 60_000)
            if runs and not len(regular.open_minutes(runs[-1][1], run[0])):
                runs[-1] = (runs[-1][0], run[1])  # nothing tradable in between: one closure across midnight or the halt
            else:
                runs.append(run)
    assert last_day is not None, "no downloaded Dukascopy days"
    return runs, last_day


def snap(t_ms: int) -> int:
    return t_ms + 60_000 if (t_ms // 60_000) % 15 == 14 else t_ms


def main() -> None:
    cfg = load_config(instrument="XAUUSD")
    runs, last_day = observed_runs(cfg)
    rows: list[tuple[int, int, str, str]] = []
    latest: dict[str, tuple[date, int, int]] = {}  # holiday -> (date, start, end)
    for s, e in runs:
        s = snap(s)
        if (e - s) < MIN_MINUTES * 60_000:
            continue
        h = holiday_of(s, e - s)
        if h is None:
            print(f"# UNMATCHED (left out): {from_ms(s).isoformat()} -> {from_ms(e).isoformat()} ({(e - s) // 60_000} min)", file=sys.stderr)
            continue
        rows.append((s, e, h[1], "dukascopy zero-volume run"))
        latest[h[1]] = (h[0], s, e)
    # projections: each holiday's latest pattern, as offsets from that holiday's Chicago midnight
    future_from = last_day + timedelta(days=1)
    for y in range(future_from.year, LAST_YEAR + 1):
        for d, name in sorted(us_holidays(y).items()):
            if d < future_from or name not in latest:
                continue
            ref_day, s, e = latest[name]
            base_ref = to_ms(datetime(ref_day.year, ref_day.month, ref_day.day, tzinfo=CHICAGO))
            base_new = to_ms(datetime(d.year, d.month, d.day, tzinfo=CHICAGO))
            rows.append((base_new + (s - base_ref), base_new + (e - base_ref), name, f"projected from {ref_day.isoformat()}"))
    missing = sorted({n for y in range(future_from.year, LAST_YEAR + 1) for d, n in us_holidays(y).items() if d >= future_from} - set(latest))
    if missing:
        print(f"# no observed pattern (not projected): {missing}", file=sys.stderr)
    rows.sort()
    text = HEADER + "".join(f"{from_ms(s).isoformat().replace('+00:00', 'Z')},{from_ms(e).isoformat().replace('+00:00', 'Z')},{n},{src}\n"
                            for s, e, n, src in rows)
    print(text, end="")
    if "--write" in sys.argv:
        path = DEFAULT_CONFIG_DIR / SESSIONS_DIR / "cme_metals_closures.csv"
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"# written {path} ({len(rows)} rows); last downloaded day {last_day}", file=sys.stderr)


if __name__ == "__main__":
    main()
