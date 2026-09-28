from datetime import datetime, timedelta

import pytest

from arven.core.time import UTC
from arven.core.timeframes import (
    Timeframe,
    bar_available_at,
    bar_close_time,
    ceil_to_bar,
    floor_to_bar,
    is_aligned,
    iter_bar_closes,
    iter_bar_opens,
    last_closed_bar_open,
)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("tf", "minutes"),
    [(Timeframe.M1, 1), (Timeframe.M5, 5), (Timeframe.M15, 15), (Timeframe.H1, 60), (Timeframe.H4, 240)],
)
def test_durations(tf, minutes):
    assert tf.duration == timedelta(minutes=minutes)
    assert tf.ms == minutes * 60_000


def test_timeframe_parses_from_exchange_strings():
    assert Timeframe("4h") is Timeframe.H4
    with pytest.raises(ValueError):
        Timeframe("2h")


def test_4h_bars_align_to_utc_midnight():
    # Binance 4h bars open at 00, 04, 08, 12, 16, 20 UTC.
    assert floor_to_bar(utc(2024, 3, 15, 10, 37), Timeframe.H4) == utc(2024, 3, 15, 8)
    assert floor_to_bar(utc(2024, 3, 15, 0, 0), Timeframe.H4) == utc(2024, 3, 15, 0)


@pytest.mark.parametrize(
    ("ts", "tf", "expected"),
    [
        (utc(2024, 1, 1, 12, 7, 30), Timeframe.M5, utc(2024, 1, 1, 12, 5)),
        (utc(2024, 1, 1, 12, 14, 59), Timeframe.M15, utc(2024, 1, 1, 12, 0)),
        (utc(2024, 1, 1, 12, 15), Timeframe.M15, utc(2024, 1, 1, 12, 15)),
        (utc(2024, 1, 1, 23, 59, 59), Timeframe.H1, utc(2024, 1, 1, 23)),
    ],
)
def test_floor_to_bar(ts, tf, expected):
    assert floor_to_bar(ts, tf) == expected


def test_ceil_to_bar():
    assert ceil_to_bar(utc(2024, 1, 1, 12, 0, 1), Timeframe.H1) == utc(2024, 1, 1, 13)
    assert ceil_to_bar(utc(2024, 1, 1, 12), Timeframe.H1) == utc(2024, 1, 1, 12)


def test_is_aligned():
    assert is_aligned(utc(2024, 1, 1, 8), Timeframe.H4)
    assert not is_aligned(utc(2024, 1, 1, 9), Timeframe.H4)
    assert not is_aligned(utc(2024, 1, 1, 8, 0, 0, 500), Timeframe.M1)


def test_bar_close_time_is_open_plus_duration():
    assert bar_close_time(utc(2024, 1, 1, 8), Timeframe.H4) == utc(2024, 1, 1, 12)


def test_bar_close_time_rejects_unaligned_open():
    with pytest.raises(ValueError, match="not aligned"):
        bar_close_time(utc(2024, 1, 1, 9), Timeframe.H4)


def test_bar_available_at_includes_delay():
    assert bar_available_at(utc(2024, 1, 1, 11), Timeframe.H1) == utc(2024, 1, 1, 12)
    assert bar_available_at(utc(2024, 1, 1, 11), Timeframe.H1, timedelta(seconds=5)) == utc(2024, 1, 1, 12, 0, 5)
    with pytest.raises(ValueError):
        bar_available_at(utc(2024, 1, 1, 11), Timeframe.H1, timedelta(seconds=-1))


# --- point-in-time guarantees -------------------------------------------------------------------


def test_last_closed_bar_at_exact_close():
    # At 12:00 the 11:00-12:00 bar has just closed and is usable.
    assert last_closed_bar_open(utc(2024, 1, 1, 12), Timeframe.H1) == utc(2024, 1, 1, 11)


def test_last_closed_bar_mid_bar_does_not_use_incomplete_bar():
    # At 12:30 the 12:00-13:00 bar is still forming; the latest usable bar is still 11:00-12:00.
    assert last_closed_bar_open(utc(2024, 1, 1, 12, 30), Timeframe.H1) == utc(2024, 1, 1, 11)


def test_4h_context_bar_not_visible_before_its_close():
    # A 1h decision at 11:00 must not see the 08:00-12:00 4h bar; it sees 04:00-08:00.
    assert last_closed_bar_open(utc(2024, 1, 1, 11), Timeframe.H4) == utc(2024, 1, 1, 4)
    assert last_closed_bar_open(utc(2024, 1, 1, 12), Timeframe.H4) == utc(2024, 1, 1, 8)


def test_last_closed_bar_respects_availability_delay():
    delay = timedelta(seconds=10)
    assert last_closed_bar_open(utc(2024, 1, 1, 12, 0, 5), Timeframe.H1, delay) == utc(2024, 1, 1, 10)
    assert last_closed_bar_open(utc(2024, 1, 1, 12, 0, 10), Timeframe.H1, delay) == utc(2024, 1, 1, 11)


@pytest.mark.parametrize("tf", list(Timeframe))
@pytest.mark.parametrize("delay_s", [0, 3, 90])
def test_last_closed_bar_is_never_available_after_t(tf, delay_s):
    delay = timedelta(seconds=delay_s)
    start = utc(2024, 1, 1)
    for step in range(0, 600, 7):  # many decision times, aligned and unaligned
        t = start + timedelta(minutes=step, seconds=step % 60)
        open_time = last_closed_bar_open(t, tf, delay)
        # The chosen bar is available at t ...
        assert bar_available_at(open_time, tf, delay) <= t
        # ... and the following bar is not (so it really is the latest usable one).
        assert bar_available_at(open_time + tf.duration, tf, delay) > t


# --- iteration ----------------------------------------------------------------------------------


def test_iter_bar_opens_half_open_interval():
    opens = list(iter_bar_opens(utc(2024, 1, 1, 0), utc(2024, 1, 1, 1), Timeframe.M15))
    assert opens == [utc(2024, 1, 1, 0), utc(2024, 1, 1, 0, 15), utc(2024, 1, 1, 0, 30), utc(2024, 1, 1, 0, 45)]


def test_iter_bar_opens_starts_at_next_boundary_when_unaligned():
    opens = list(iter_bar_opens(utc(2024, 1, 1, 0, 1), utc(2024, 1, 1, 3), Timeframe.H1))
    assert opens == [utc(2024, 1, 1, 1), utc(2024, 1, 1, 2)]


def test_iter_bar_closes_one_day_of_1h_decisions():
    closes = list(iter_bar_closes(utc(2024, 1, 1), utc(2024, 1, 2), Timeframe.H1))
    assert len(closes) == 24
    assert closes[0] == utc(2024, 1, 1, 0)
    assert closes[-1] == utc(2024, 1, 1, 23)


def test_iteration_across_leap_day_has_no_gaps():
    opens = list(iter_bar_opens(utc(2024, 2, 28), utc(2024, 3, 1), Timeframe.H4))
    assert len(opens) == 12
    assert all(b - a == timedelta(hours=4) for a, b in zip(opens, opens[1:]))


def test_empty_iteration_when_end_not_after_start():
    assert list(iter_bar_opens(utc(2024, 1, 1), utc(2024, 1, 1), Timeframe.H1)) == []
