"""The news countdown's history (arven.event_moves): window arithmetic, trading time on gold, the ordinary-day
baseline, no look-ahead, and the summary."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from arven.core.macro_config import MacroEvent
from arven.core.sessions import SessionCalendar
from arven.core.time import UTC, to_ms
from arven.event_moves import (
    M15, Bars, baseline, due_reminders, event_rows, expected_opens, summarize, upcoming, window,
)

DAY = 86_400_000
GOLD = SessionCalendar("cme_metals")


def ms(*a: int) -> int:
    return to_ms(datetime(*a, tzinfo=UTC))


def flat_bars(start: int, end: int, price: float = 100.0, width: float = 1.0) -> Bars:
    """Every 15m bar in [start, end): open = close = price, high/low = price +- width/2."""
    t = np.arange(start, end, M15, dtype=np.int64)
    p = np.full(len(t), price)
    return Bars(t, p.copy(), p + width / 2, p - width / 2, p.copy())


def with_bar(b: Bars, t: int, o: float, h: float, lo: float, c: float) -> Bars:
    i = int(np.searchsorted(b.open_time_ms, t))
    assert b.open_time_ms[i] == t
    arrs = [x.copy() for x in (b.open, b.high, b.low, b.close)]
    for a, v in zip(arrs, (o, h, lo, c), strict=True):
        a[i] = v
    return Bars(b.open_time_ms, *arrs)


def test_window_range_and_move_by_hand():
    t0 = ms(2024, 1, 10, 13, 30)
    b = flat_bars(t0 - DAY, t0 + DAY)
    b = with_bar(b, t0, 100.0, 103.0, 99.0, 102.0)  # the release bar
    b = with_bar(b, t0 + 3 * M15, 101.0, 101.5, 97.0, 98.0)  # the 4th bar of the hour
    rng, mv = window(b, t0, 60, now_ms=t0 + DAY)
    assert rng == pytest.approx((103.0 - 97.0) / 100.0 * 100) and mv == pytest.approx(2.0)
    rng15, mv15 = window(b, t0, 15, now_ms=t0 + DAY)
    assert rng15 == pytest.approx(4.0) and mv15 == pytest.approx(2.0)


def test_window_needs_every_bar_and_a_closed_window():
    t0 = ms(2024, 1, 10, 13, 30)
    b = flat_bars(t0 - DAY, t0 + DAY)
    assert window(b, t0, 60, now_ms=t0 + 60 * 60_000) is not None  # the last bar closes exactly at now
    assert window(b, t0, 60, now_ms=t0 + 60 * 60_000 - 1) is None  # still forming
    keep = b.open_time_ms != t0 + 2 * M15
    gap = Bars(*(x[keep] for x in (b.open_time_ms, b.open, b.high, b.low, b.close)))
    assert window(gap, t0, 60, now_ms=t0 + DAY) is None and window(gap, t0, 15, now_ms=t0 + DAY) is not None
    assert window(b, t0 + 60_000, 15, now_ms=t0 + DAY) is None  # not on the 15m grid


def test_gold_counts_trading_time_across_the_daily_halt_but_not_a_weekend():
    t = ms(2024, 7, 16, 20)  # Tuesday 16:00 New York; the halt is 21:00-22:00 UTC
    opens = expected_opens(t, 240, GOLD)
    assert len(opens) == 16 and opens[3] == ms(2024, 7, 16, 20, 45) and opens[4] == ms(2024, 7, 16, 22)
    assert expected_opens(ms(2024, 7, 12, 20), 240, GOLD) is None  # Friday: would run into the weekend
    assert expected_opens(ms(2024, 7, 16, 21, 15), 60, GOLD) is None  # closed at the start
    assert len(expected_opens(t, 240, None)) == 16 and expected_opens(t, 240, None)[4] == ms(2024, 7, 16, 21)


def test_baseline_uses_earlier_event_free_weekdays_only():
    t0 = ms(2024, 3, 13, 12, 30)  # a Wednesday
    b = flat_bars(t0 - 60 * DAY, t0 + 30 * DAY, width=1.0)  # every ordinary window: range 1 %
    for k in range(1, 30):  # later days are wild - they must not count
        b = with_bar(b, t0 + k * DAY, 100.0, 150.0, 50.0, 100.0)
    event_day = (t0 - DAY) // DAY  # the day before was an event day: wild, but excluded
    b = with_bar(b, t0 - DAY, 100.0, 150.0, 50.0, 100.0)
    assert baseline(b, t0, 15, {event_day}, now_ms=t0 + 40 * DAY) == pytest.approx(1.0)
    assert baseline(b, t0, 15, set(), now_ms=t0 + 40 * DAY) == pytest.approx(1.0)  # one wild day of 20 moves no median
    short = flat_bars(t0 - 3 * DAY, t0 + DAY)
    assert baseline(short, t0, 15, set(), now_ms=t0 + DAY) is None  # fewer than 5 usable days


def test_event_rows_only_count_closed_horizons_and_ignore_later_data():
    t0 = ms(2024, 3, 13, 12, 30)
    events = [MacroEvent(t0, "CPI", ""), MacroEvent(t0 + 30 * DAY, "CPI", "")]
    b = flat_bars(t0 - 60 * DAY, t0 + 40 * DAY)
    now = t0 + 60 * 60_000
    rows = event_rows(b, events, now)
    assert len(rows) == 1 and set(rows[0]["horizons"]) == {"15", "60"}  # 4 h not closed yet, the later event in the future
    keep = b.open_time_ms + M15 <= now
    truncated = Bars(*(x[keep] for x in (b.open_time_ms, b.open, b.high, b.low, b.close)))
    assert event_rows(truncated, events, now) == rows


def test_summarize_by_hand():
    rows = [
        {"time_ms": 1, "type": "FOMC", "horizons": {"60": {"range": 2.0, "move": 1.0, "baseline": 1.0}}},
        {"time_ms": 2, "type": "FOMC", "horizons": {"60": {"range": 4.0, "move": 0.5, "baseline": 1.0}}},
        {"time_ms": 3, "type": "FOMC", "horizons": {"60": {"range": 0.5, "move": 0.1, "baseline": None}}},
    ]
    s = summarize(rows, horizons=(60,))
    f = s["FOMC"]["60"]
    assert f["n"] == 3 and f["median_range"] == 2.0 and f["max_range"] == 4.0 and f["max_time_ms"] == 2
    assert f["median_move"] == 0.5 and f["median_baseline"] == 1.0 and f["median_ratio"] == 3.0 and f["share_above_baseline"] == 1.0
    assert f["n_baseline"] == 2 and s["CPI"]["60"] == {"n": 0}


def test_upcoming_and_reminder_timing():
    ev = [MacroEvent(ms(2026, 10, 28, 18), "FOMC", ""), MacroEvent(ms(2026, 11, 6, 13, 30), "NFP", "")]
    now = ms(2026, 10, 28, 17, 0)
    assert [e["type"] for e in upcoming(ev, now)] == ["FOMC", "NFP"]
    assert due_reminders(ev, now, 60) == [ev[0]]
    assert due_reminders(ev, now - 1, 60) == [] and due_reminders(ev, ms(2026, 10, 28, 18), 60) == []
