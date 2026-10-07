"""Phase 5 gate contribution: LiveEventClock's catch-up/backfill, tie-rule, and restart-safety."""

from __future__ import annotations

import pytest

from arven.core.time import from_ms
from arven.core.timeframes import Timeframe
from arven.engine.clock import LiveEventClock

HOUR = 3_600_000
MIN = 60_000


def box_now(start_ms: int):
    box = [from_ms(start_ms)]

    def now_fn():
        return box[0]

    def set_ms(t_ms: int) -> None:
        box[0] = from_ms(t_ms)

    return now_fn, set_ms


def drain(clock: LiveEventClock) -> list:
    out = []
    while (e := clock.advance()) is not None:
        out.append(e)
    return out


def test_nothing_due_yet_returns_none():
    now_fn, _ = box_now(0)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=0, now_fn=now_fn)
    assert clock.advance() is None


def test_one_bar_becomes_due_exactly_at_its_close():
    now_fn, set_ms = box_now(0)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=0, now_fn=now_fn)
    set_ms(HOUR)
    e = clock.advance()
    assert e is not None and e.close_ms == HOUR and e.timeframe == Timeframe.H1
    assert clock.advance() is None  # only one bar due, no more


def test_now_ms_tracks_the_last_returned_event():
    now_fn, set_ms = box_now(0)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=0, now_fn=now_fn)
    with pytest.raises(RuntimeError):
        _ = clock.now_ms
    set_ms(HOUR)
    clock.advance()
    assert clock.now_ms == HOUR


def test_catch_up_drains_every_missed_bar_oldest_first():
    # process was "down"; wall clock jumps straight to 3 hours later - all 3 missed 1h closes must be
    # emitted, in order, on successive advance() calls (the "backfill gaps before emitting" requirement).
    now_fn, set_ms = box_now(0)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=0, now_fn=now_fn)
    set_ms(3 * HOUR)
    events = drain(clock)
    assert [e.close_ms for e in events] == [HOUR, 2 * HOUR, 3 * HOUR]


def test_coincident_closes_are_ordered_coarsest_timeframe_first():
    now_fn, set_ms = box_now(0)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1, Timeframe.H4), start_after_ms=0, now_fn=now_fn)
    set_ms(4 * HOUR)
    events = drain(clock)
    closes = [(e.close_ms, e.timeframe) for e in events]
    assert closes == [
        (HOUR, Timeframe.H1), (2 * HOUR, Timeframe.H1), (3 * HOUR, Timeframe.H1),
        (4 * HOUR, Timeframe.H4), (4 * HOUR, Timeframe.H1),
    ]


def test_restart_from_a_later_start_after_ms_never_replays_already_processed_bars():
    now_fn, _ = box_now(3 * HOUR)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=2 * HOUR, now_fn=now_fn)
    events = drain(clock)
    assert [e.close_ms for e in events] == [3 * HOUR]  # the 1h/2h closes were already processed before restart


def test_availability_delay_holds_an_already_closed_bar_back():
    now_fn, set_ms = box_now(0)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=0, delay_ms=30_000, now_fn=now_fn)
    set_ms(HOUR)  # closed, but not yet available under the 30s delay
    assert clock.advance() is None
    set_ms(HOUR + 30_000)
    e = clock.advance()
    assert e is not None and e.available_at_ms == HOUR + 30_000


def test_polling_again_with_no_new_time_elapsed_returns_none_without_re_emitting():
    now_fn, set_ms = box_now(0)
    clock = LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=0, now_fn=now_fn)
    set_ms(HOUR)
    first = clock.advance()
    assert first is not None
    assert clock.advance() is None
    assert clock.advance() is None  # idempotent: polling again changes nothing


def test_rejects_empty_symbol_or_timeframes_or_duplicates_or_negative_delay():
    with pytest.raises(ValueError):
        LiveEventClock("", (Timeframe.H1,), start_after_ms=0)
    with pytest.raises(ValueError):
        LiveEventClock("BTCUSDT", (), start_after_ms=0)
    with pytest.raises(ValueError):
        LiveEventClock("BTCUSDT", (Timeframe.H1, Timeframe.H1), start_after_ms=0)
    with pytest.raises(ValueError):
        LiveEventClock("BTCUSDT", (Timeframe.H1,), start_after_ms=0, delay_ms=-1)
