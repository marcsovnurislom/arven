"""The Sessions page's pure logic (arven.web.sessions): market state at the transitions, the centres' local hours across
daylight saving, and the activity grid (buckets, closed bars only)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from arven.core.sessions import SessionCalendar
from arven.core.time import UTC, to_ms
from arven.web.sessions import CENTRES, activity_grid, centre_status, market_state, next_holiday

HOUR = 3_600_000
GOLD = SessionCalendar("cme_metals")


def ms(*a: int) -> int:
    return to_ms(datetime(*a, tzinfo=UTC))


def centre(cid: str):
    return next(c for c in CENTRES if c.id == cid)


def test_btc_is_always_open():
    s = market_state(SessionCalendar("24x7"), ms(2024, 1, 13, 12))
    assert s["state"] == "always_open" and s["open"] is True and s["next_change_ms"] is None


def test_gold_friday_close_and_sunday_reopen_in_winter():
    s = market_state(GOLD, ms(2024, 1, 12, 21, 59))  # Friday 16:59 New York (EST)
    assert s["state"] == "open" and s["next_change_ms"] == ms(2024, 1, 12, 22) and s["closure_ends_ms"] == ms(2024, 1, 14, 23)
    s = market_state(GOLD, ms(2024, 1, 12, 22))  # the close itself is already closed
    assert s["state"] == "weekend" and s["open"] is False and s["next_change_ms"] == ms(2024, 1, 14, 23)
    s = market_state(GOLD, ms(2024, 1, 14, 23))  # Sunday 18:00 New York: open again
    assert s["state"] == "open"


def test_gold_daily_halt_in_summer_is_an_hour_earlier_in_utc():
    s = market_state(GOLD, ms(2024, 7, 16, 21, 30))  # Tuesday 17:30 New York (EDT)
    assert s["state"] == "halt" and s["next_change_ms"] == ms(2024, 7, 16, 22)
    assert market_state(GOLD, ms(2024, 7, 16, 20, 59))["next_change_ms"] == ms(2024, 7, 16, 21)


def test_gold_holiday_early_close_merged_with_the_halt_is_named():
    holidays = ((ms(2026, 11, 26, 19, 30), ms(2026, 11, 26, 22), "Thanksgiving"),)
    cal = SessionCalendar("cme_metals", extra_closures=tuple((s, e) for s, e, _ in holidays))
    s = market_state(cal, ms(2026, 11, 26, 20), holidays)
    assert s["state"] == "holiday" and s["reason"] == "Thanksgiving" and s["next_change_ms"] == ms(2026, 11, 26, 23)
    assert market_state(cal, ms(2026, 11, 26, 19), holidays)["next_change_ms"] == ms(2026, 11, 26, 19, 30)
    assert next_holiday(holidays, ms(2026, 11, 1))["reason"] == "Thanksgiving"
    assert next_holiday(holidays, ms(2026, 11, 26, 22)) is None


def test_london_follows_british_summer_time():
    s = centre_status(centre("london"), ms(2024, 3, 25, 7, 30))  # Monday 07:30 GMT
    assert s["open"] is False and s["next_change_ms"] == ms(2024, 3, 25, 8)
    s = centre_status(centre("london"), ms(2024, 4, 1, 7, 30))  # Monday 08:30 BST
    assert s["open"] is True and s["next_change_ms"] == ms(2024, 4, 1, 16)


def test_new_york_weekend_reopens_on_monday_morning():
    s = centre_status(centre("new_york"), ms(2024, 7, 13, 15))  # Saturday
    assert s["open"] is False and s["next_change_ms"] == ms(2024, 7, 15, 12)


def test_sydney_opens_on_sunday_evening_utc_after_its_dst_ended():
    s = centre_status(centre("sydney"), ms(2024, 4, 7, 20))  # Monday 06:00 AEST
    assert s["open"] is False and s["next_change_ms"] == ms(2024, 4, 7, 21)


def test_tokyo_closes_at_18_local():
    s = centre_status(centre("tokyo"), ms(2024, 7, 12, 8, 59))
    assert s["open"] is True and s["next_change_ms"] == ms(2024, 7, 12, 9)
    assert s["open_local"] == "09:00" and s["close_local"] == "18:00"


def _bars():
    t = np.array([ms(2024, 1, 15, 10), ms(2024, 1, 22, 10), ms(2024, 1, 16, 0), ms(2024, 1, 17, 5)], dtype=np.int64)
    o = np.array([100.0, 100.0, 100.0, np.nan])
    h = np.array([102.0, 101.0, 110.0, 1.0])
    lo = np.array([99.0, 100.0, 90.0, 1.0])
    return t, o, h, lo, t + HOUR - 1


def test_activity_grid_buckets_by_utc_weekday_and_hour():
    t, o, h, lo, ct = _bars()
    g = activity_grid(t, o, h, lo, ct, now_ms=ms(2024, 2, 1))
    assert g["mean_range_pct"][0][10] == pytest.approx(2.0) and g["n"][0][10] == 2  # two Mondays 10:00: 3 % and 1 %
    assert g["mean_range_pct"][1][0] == pytest.approx(20.0)  # Tuesday 00:00
    assert g["mean_range_pct"][2][5] is None and g["n"][2][5] == 0  # a NaN bar is not counted
    assert g["bars"] == 3 and sum(map(sum, g["n"])) == 3


def test_activity_grid_ignores_bars_not_closed_yet():
    t, o, h, lo, ct = _bars()
    now = ms(2024, 1, 16, 0, 30)  # the Tuesday 00:00 bar is still forming; the 22nd is in the future
    full = activity_grid(t, o, h, lo, ct, now_ms=now)
    keep = ct < now
    truncated = activity_grid(t[keep], o[keep], h[keep], lo[keep], ct[keep], now_ms=now)
    assert full == truncated
    assert full["n"][0][10] == 1 and full["mean_range_pct"][1][0] is None


def test_activity_grid_without_bars_is_empty_not_zero():
    e = np.array([], dtype=np.int64)
    g = activity_grid(e, e.astype(float), e.astype(float), e.astype(float), e, now_ms=ms(2024, 1, 1))
    assert g["bars"] == 0 and g["from_ms"] is None and all(v is None for row in g["mean_range_pct"] for v in row)
