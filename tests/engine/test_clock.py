"""Phase 1 gate: ordering, availability, and no-look-ahead for SimulatedEventClock."""

from __future__ import annotations

import pytest

from arven.core.timeframes import Timeframe
from arven.engine.clock import SimulatedEventClock

HOUR = 3_600_000
MIN = 60_000


def drain(clock: SimulatedEventClock) -> list:
    out = []
    while True:
        e = clock.advance()
        if e is None:
            return out
        out.append(e)


# --- construction validation -----------------------------------------------------------------------


def test_rejects_empty_symbol():
    with pytest.raises(ValueError):
        SimulatedEventClock("", (Timeframe.H1,), 0, HOUR)


def test_rejects_no_timeframes():
    with pytest.raises(ValueError):
        SimulatedEventClock("BTCUSDT", (), 0, HOUR)


def test_rejects_duplicate_timeframes():
    with pytest.raises(ValueError):
        SimulatedEventClock("BTCUSDT", (Timeframe.H1, Timeframe.H1), 0, 4 * HOUR)


def test_rejects_negative_delay():
    with pytest.raises(ValueError):
        SimulatedEventClock("BTCUSDT", (Timeframe.H1,), 0, HOUR, delay_ms=-1)


def test_rejects_end_not_after_start():
    with pytest.raises(ValueError):
        SimulatedEventClock("BTCUSDT", (Timeframe.H1,), HOUR, HOUR)


# --- now_ms / started, mirroring the legacy SimulationClock's own contract -------------------------


def test_now_ms_before_start_raises():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.H1,), 0, 2 * HOUR)
    assert not clock.started
    with pytest.raises(RuntimeError):
        _ = clock.now_ms


def test_now_ms_tracks_the_last_advanced_event_and_stays_put_after_exhaustion():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.H1,), 0, 2 * HOUR)
    first = clock.advance()
    assert clock.now_ms == first.close_ms == HOUR
    second = clock.advance()
    assert clock.now_ms == second.close_ms == 2 * HOUR
    assert clock.advance() is None
    assert clock.now_ms == 2 * HOUR  # unchanged once exhausted


# --- single timeframe: a plain, strictly increasing grid -------------------------------------------


def test_single_timeframe_emits_one_event_per_bar_in_order():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.H1,), 0, 3 * HOUR)
    events = drain(clock)
    assert [e.close_ms for e in events] == [HOUR, 2 * HOUR, 3 * HOUR]
    assert all(e.timeframe == Timeframe.H1 and e.symbol == "BTCUSDT" for e in events)


# --- the documented tie rule: coarsest timeframe first at a shared close_ms ------------------------


def test_coincident_closes_are_ordered_coarsest_timeframe_first():
    # 1h and 4h both close at 4h; 1h also closes at 1h/2h/3h with nothing to tie against.
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.H1, Timeframe.H4), 0, 4 * HOUR)
    events = drain(clock)
    closes = [(e.close_ms, e.timeframe) for e in events]
    assert closes == [
        (HOUR, Timeframe.H1),
        (2 * HOUR, Timeframe.H1),
        (3 * HOUR, Timeframe.H1),
        (4 * HOUR, Timeframe.H4),  # coarsest first ...
        (4 * HOUR, Timeframe.H1),  # ... then the finer timeframe sharing the same instant
    ]


def test_three_timeframes_sharing_one_instant_are_fully_ordered_coarse_to_fine():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1, Timeframe.H4), 0, 4 * HOUR)
    events = drain(clock)
    at_4h = [e.timeframe for e in events if e.close_ms == 4 * HOUR]
    assert at_4h == [Timeframe.H4, Timeframe.H1, Timeframe.M15]


def test_event_close_ms_is_never_decreasing_across_the_whole_sequence():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4), 0, 8 * HOUR)
    events = drain(clock)
    closes = [e.close_ms for e in events]
    assert closes == sorted(closes)


# --- availability -------------------------------------------------------------------------------------


def test_available_at_is_close_ms_when_delay_is_zero():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.H1,), 0, HOUR)
    e = clock.advance()
    assert e.available_at_ms == e.close_ms


def test_available_at_adds_the_configured_delay_for_every_timeframe():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1), 0, HOUR, delay_ms=5_000)
    for e in drain(clock):
        assert e.available_at_ms == e.close_ms + 5_000


# --- determinism / no hidden randomness -----------------------------------------------------------


def test_identical_construction_yields_byte_identical_sequences():
    a = drain(SimulatedEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1, Timeframe.H4), 0, 8 * HOUR))
    b = drain(SimulatedEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1, Timeframe.H4), 0, 8 * HOUR))
    assert a == b


def test_timeframe_argument_order_does_not_affect_the_resulting_sequence():
    a = drain(SimulatedEventClock("BTCUSDT", (Timeframe.H1, Timeframe.H4, Timeframe.M15), 0, 4 * HOUR))
    b = drain(SimulatedEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H4, Timeframe.H1), 0, 4 * HOUR))
    assert a == b


# --- events property for tooling/tests --------------------------------------------------------------


def test_events_property_exposes_the_full_precomputed_sequence_without_advancing():
    clock = SimulatedEventClock("BTCUSDT", (Timeframe.H1,), 0, 2 * HOUR)
    assert not clock.started
    assert len(clock.events) == 2
    assert not clock.started  # reading .events must not itself advance the clock
