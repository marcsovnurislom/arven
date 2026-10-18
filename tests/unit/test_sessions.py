"""Session calendars (arven.core.sessions): the CME metals rule is checked against moments observed in the real
Dukascopy XAUUSD feed (zero-volume runs, 2024), and 24x7 must degenerate to the plain UTC grid."""

from datetime import datetime

import numpy as np
import pytest

from arven.core.sessions import SessionCalendar, cme_metals_regular_closures
from arven.core.time import UTC, to_ms
from arven.core.timeframes import Timeframe

MIN = 60_000
CME = SessionCalendar("cme_metals")
ALWAYS = SessionCalendar()


def ms(*args) -> int:
    return to_ms(datetime(*args, tzinfo=UTC))


@pytest.mark.parametrize(
    ("moment", "open_"),
    [
        # Friday 2024-03-08 (winter, New York = UTC-5): last minute 21:59, closed from 22:00 (17:00 New York)
        ((2024, 3, 8, 21, 59), True),
        ((2024, 3, 8, 22, 0), False),
        ((2024, 3, 9, 12, 0), False),  # Saturday
        # Sunday 2024-03-10, after the US switch to summer time that morning (UTC-4): opens 22:00 UTC = 18:00 NY
        ((2024, 3, 10, 21, 59), False),
        ((2024, 3, 10, 22, 0), True),
        # Monday 2024-03-11 (summer): daily halt 21:00-22:00 UTC
        ((2024, 3, 11, 20, 59), True),
        ((2024, 3, 11, 21, 0), False),
        ((2024, 3, 11, 21, 59), False),
        ((2024, 3, 11, 22, 0), True),
        # Tuesday 2024-01-16 (winter): halt 22:00-23:00 UTC
        ((2024, 1, 16, 21, 59), True),
        ((2024, 1, 16, 22, 0), False),
        ((2024, 1, 16, 23, 0), True),
        # Friday 2024-07-12 (summer): weekend close at 21:00 UTC
        ((2024, 7, 12, 20, 59), True),
        ((2024, 7, 12, 21, 0), False),
    ],
)
def test_cme_metals_regular_hours_match_observed_feed(moment, open_):
    assert CME.is_open(ms(*moment)) is open_


def test_24x7_is_always_open_and_degenerates_to_the_utc_grid():
    t = np.arange(ms(2024, 3, 8), ms(2024, 3, 12), MIN)
    assert ALWAYS.is_open(t).all()
    assert np.array_equal(ALWAYS.open_minutes(ms(2024, 3, 8), ms(2024, 3, 12)), t)
    opens = ALWAYS.bar_opens(Timeframe.H4, ms(2024, 3, 8), ms(2024, 3, 12))
    assert np.array_equal(opens, np.arange(ms(2024, 3, 8), ms(2024, 3, 12), Timeframe.H4.ms))
    assert (ALWAYS.expected_minutes(Timeframe.H4, opens) == 240).all()
    assert ALWAYS.next_bar_open(Timeframe.M15, ms(2024, 3, 8, 21, 45)) == ms(2024, 3, 8, 22, 0)
    assert ALWAYS.closed_windows(ms(2024, 1, 1), ms(2025, 1, 1)) == []


def test_expected_minutes_count_only_open_minutes():
    summer_monday_20h = ms(2024, 3, 11, 20)  # 20:00-24:00 contains the 21:00-22:00 halt
    friday_20h = ms(2024, 7, 12, 20)  # 20:00-21:00 open, then the weekend close
    sunday_20h = ms(2024, 7, 14, 20)  # 22:00-24:00 open after the weekend
    got = CME.expected_minutes(Timeframe.H4, np.array([summer_monday_20h, friday_20h, sunday_20h]))
    assert got.tolist() == [180, 60, 120]


def test_bar_opens_skip_closed_buckets_and_next_bar_crosses_the_weekend():
    opens = CME.bar_opens(Timeframe.H1, ms(2024, 7, 12, 18), ms(2024, 7, 14, 23, 30))
    assert opens.tolist() == [ms(2024, 7, 12, 18), ms(2024, 7, 12, 19), ms(2024, 7, 12, 20), ms(2024, 7, 14, 22), ms(2024, 7, 14, 23)]
    assert CME.next_bar_open(Timeframe.M15, ms(2024, 7, 12, 20, 45)) == ms(2024, 7, 14, 22, 0)
    nxt = CME.next_bar_opens(Timeframe.M15, np.array([ms(2024, 7, 12, 20, 30), ms(2024, 7, 12, 20, 45), ms(2024, 7, 15, 20, 45)]))
    assert nxt.tolist() == [ms(2024, 7, 12, 20, 45), ms(2024, 7, 14, 22, 0), ms(2024, 7, 15, 22, 0)]


def test_extra_closures_add_holidays_on_top_of_the_regular_rule():
    good_friday = (ms(2024, 3, 28, 21), ms(2024, 3, 31, 22))  # Thursday halt -> Sunday open
    cal = SessionCalendar("cme_metals", (good_friday,))
    assert CME.is_open(ms(2024, 3, 29, 12)) is True
    assert cal.is_open(ms(2024, 3, 29, 12)) is False
    assert cal.is_open(ms(2024, 3, 28, 20, 59)) is True
    assert cal.next_bar_open(Timeframe.H1, ms(2024, 3, 28, 20)) == ms(2024, 3, 31, 22)
    windows = cal.closed_windows(ms(2024, 3, 28), ms(2024, 4, 1))
    assert (ms(2024, 3, 28, 21), ms(2024, 3, 31, 22)) in windows  # merged with the regular weekend close


def test_is_open_vectorised_equals_scalar():
    t = np.arange(ms(2024, 3, 7), ms(2024, 3, 13), 7 * MIN)
    vec = CME.is_open(t)
    assert vec.tolist() == [CME.is_open(int(x)) for x in t]


def test_regular_closures_are_sorted_and_disjoint_over_years():
    w = cme_metals_regular_closures(ms(2020, 1, 1), ms(2027, 1, 1))
    starts = np.array([s for s, _ in w])
    ends = np.array([e for _, e in w])
    assert (np.diff(starts) > 0).all() and (starts[1:] >= ends[:-1]).all() and (ends > starts).all()
    assert all(s % MIN == 0 and e % MIN == 0 for s, e in w)


def test_queries_outside_the_precomputed_horizon_still_work():
    saturday, wednesday = ms(2040, 3, 10, 12), ms(2040, 3, 7, 12)
    assert [datetime.fromtimestamp(t / 1000, UTC).weekday() for t in (saturday, wednesday)] == [5, 2]
    assert CME.is_open(saturday) is False
    assert CME.is_open(wednesday) is True


@pytest.mark.parametrize("bad", [((0, 30_000),), ((60_000, 60_000),)])
def test_invalid_closures_rejected(bad):
    with pytest.raises(ValueError):
        SessionCalendar("cme_metals", bad)


def test_24x7_cannot_have_closures_and_unknown_kind_rejected():
    with pytest.raises(ValueError):
        SessionCalendar("24x7", ((0, MIN),))
    with pytest.raises(ValueError):
        SessionCalendar("nyse")  # type: ignore[arg-type]
