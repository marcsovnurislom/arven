"""Signals that do not contradict each other (arven.live.conflicts): what counts as active, the timeframe priority for
simultaneous signals, and the same strategy never conflicting with itself."""

from __future__ import annotations

from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.live.conflicts import ActiveSignal, check, end_of, priority

H = 3_600_000


def sig(sid: str, strategy: str, tf: str, side: int, start: int, end: int | None = None, order: int = 0) -> ActiveSignal:
    return ActiveSignal(sid, strategy, strategy.upper(), tf, side, start, end, priority(tf, order))


def test_an_opposite_open_signal_of_another_strategy_is_a_conflict_a_same_side_one_confirms():
    new = sig("n", "s7", "15m", 1, 10 * H, order=0)
    others = [sig("a", "s7_4h", "4h", -1, 2 * H, None, 2), sig("b", "s5", "15m", 1, 9 * H, None, 1), sig("c", "s6", "15m", -1, 1 * H, 5 * H, 3)]
    opposite, same = check(new, others)
    assert [o.signal_id for o in opposite] == ["a"]  # c closed before the new signal: not active any more
    assert [o.signal_id for o in same] == ["b"]


def test_signals_that_start_later_or_belong_to_the_same_strategy_do_not_count():
    new = sig("n", "s7", "15m", 1, 10 * H)
    assert check(new, [sig("x", "s5", "15m", -1, 11 * H), sig("y", "s7", "15m", -1, 5 * H)]) == ([], [])


def test_of_two_simultaneous_opposite_signals_the_higher_timeframe_wins():
    long_15m = sig("l", "s7", "15m", 1, 10 * H, order=0)
    short_4h = sig("s", "s7_4h", "4h", -1, 10 * H, order=2)
    assert [o.signal_id for o in check(long_15m, [short_4h])[0]] == ["s"]  # the 15m long is the one flagged
    assert check(short_4h, [long_15m]) == ([], [])  # the 4h short is not
    a = sig("a", "s4", "15m", 1, 10 * H, order=0)
    b = sig("b", "s5", "15m", -1, 10 * H, order=1)
    assert check(a, [b]) == ([], []) and [o.signal_id for o in check(b, [a])[0]] == ["a"]  # same timeframe: config order


def test_end_of_takes_the_close_or_the_cancellation():
    ups = [SignalUpdate("x", 5 * H, SignalUpdateKind.TP_HIT, "level=TP1"), SignalUpdate("x", 7 * H, SignalUpdateKind.CLOSED, "reason=STOP")]
    assert end_of(ups) == 7 * H and end_of(ups[:1]) is None
    assert end_of([SignalUpdate("x", 3 * H, SignalUpdateKind.CANCELLED, "reason=expired")]) == 3 * H
