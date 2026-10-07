"""Phase 3: orchestration of the event-driven backtest loop beyond the 1h equivalence proof - genuine
multi-timeframe dispatch (each provider only on its own timeframe, coarsest-first at shared instants),
``prepare`` per provider, skipped timeframes, and every validation / degenerate input."""

from __future__ import annotations

from typing import Any

import pytest
from bt_helpers import HOUR, Scripted, app_config, bt_config, features_for, long_signal, make_market, window

from arven.backtest.engine import Backtester, decision_grid
from arven.backtest.errors import ConfigurationError, DataError, LookAheadError, SignalError
from arven.backtest.event_engine import EventBacktester, WindowEventClock, timeframe_grid
from arven.backtest.provider import DecisionContext, PrepareInfo
from arven.backtest.types import EquityKind, OrderStatus
from arven.core.signal import Signal
from arven.core.timeframes import Timeframe
from arven.engine.clock import SimulatedEventClock
from arven.engine.events import BarCloseEvent

MIN15 = 15 * 60_000


class Counting:
    """Records every prepare/decide call into a shared log; never trades unless scripted."""

    def __init__(self, name: str, log: list, signals: dict[int, Signal] | None = None) -> None:
        self.name, self.log, self.signals = name, log, signals or {}
        self.prepared: list[PrepareInfo] = []
        self.calls: list[tuple[int, int]] = []

    def describe(self) -> dict[str, Any]:
        return {"name": self.name}

    def prepare(self, info: PrepareInfo) -> None:
        self.prepared.append(info)
        self.log.append(("prepare", self.name))

    def decide(self, ctx: DecisionContext) -> Signal | None:
        self.calls.append((ctx.now_ms, ctx.index))
        self.log.append((ctx.now_ms, self.name))
        return self.signals.get(ctx.now_ms)


def _setup(hours: int):
    win = window(hours)
    return win, make_market(hours), features_for(win)


def _bt(win, market, feats):
    return EventBacktester(app_config(), bt_config(), win, market, feats)


# --- genuine multi-timeframe dispatch ------------------------------------------------------------------


def test_each_provider_is_called_only_on_its_own_timeframe_events():
    win, market, feats = _setup(6)
    log: list = []
    h1, m15 = Counting("h1", log), Counting("m15", log)
    clock = WindowEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1), win.start_ms, win.end_ms)
    res = _bt(win, market, feats).run(clock, {Timeframe.H1: h1, Timeframe.M15: m15})

    assert [t for t, _ in h1.calls] == [win.start_ms + k * HOUR for k in range(6)]
    assert [t for t, _ in m15.calls] == [win.start_ms + k * MIN15 for k in range(24)]
    assert [i for _, i in h1.calls] == list(range(6))  # ctx.index counts the provider's own decisions
    assert [i for _, i in m15.calls] == list(range(24))
    assert res.n_decisions == 30
    assert sum(p.kind == EquityKind.DECISION for p in res.equity) == 30


def test_coarsest_timeframe_is_dispatched_first_at_a_shared_instant():
    win, market, feats = _setup(8)
    log: list = []
    provs = {tf: Counting(str(tf), log) for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4)}
    clock = WindowEventClock("BTCUSDT", (Timeframe.H1, Timeframe.M15, Timeframe.H4), win.start_ms, win.end_ms)
    _bt(win, market, feats).run(clock, provs)

    decisions = [e for e in log if e[0] != "prepare"]
    times = [t for t, _ in decisions]
    assert times == sorted(times)
    for boundary in (win.start_ms, win.start_ms + 4 * HOUR):  # T0 is 4h-aligned
        assert [n for t, n in decisions if t == boundary] == ["4h", "1h", "15m"]
    assert [n for t, n in decisions if t == win.start_ms + HOUR] == ["1h", "15m"]
    assert [n for t, n in decisions if t == win.start_ms + HOUR + MIN15] == ["15m"]
    assert len(provs[Timeframe.H4].calls) == 2 and len(provs[Timeframe.H1].calls) == 8 and len(provs[Timeframe.M15].calls) == 32


def test_prepare_is_called_once_per_provider_before_any_decision_with_its_own_grid():
    win, market, feats = _setup(8)
    log: list = []
    h4, m15 = Counting("h4", log), Counting("m15", log)
    clock = WindowEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H4), win.start_ms, win.end_ms)
    _bt(win, market, feats).run(clock, {Timeframe.M15: m15, Timeframe.H4: h4})

    assert log[:2] == [("prepare", "h4"), ("prepare", "m15")]  # coarsest first, before any decide
    assert all(e[0] != "prepare" for e in log[2:])
    for p, tf in ((h4, Timeframe.H4), (m15, Timeframe.M15)):
        assert len(p.prepared) == 1
        info = p.prepared[0]
        assert list(info.grid_ms) == [t for t, _ in p.calls] == list(timeframe_grid(win.start_ms, win.end_ms, tf))
        assert info.window_end_ms == win.end_ms and info.first_ready_ms == feats.first_ready_ms


def test_events_of_unregistered_timeframes_are_skipped_entirely():
    win, market, feats = _setup(6)
    h1 = Counting("h1", [])
    clock = WindowEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1, Timeframe.H4), win.start_ms, win.end_ms)
    res = _bt(win, market, feats).run(clock, {Timeframe.H1: h1})
    assert [t for t, _ in h1.calls] == list(decision_grid(win))
    assert res.n_decisions == 6
    assert [p.time_ms for p in res.equity if p.kind == EquityKind.DECISION] == list(decision_grid(win))


def test_two_providers_entering_at_the_same_instant_open_only_one_position():
    """One account, one net position (no pyramiding): the coarser provider's entry is submitted first, the
    finer one's at the same instant is rejected as position_open, exactly like a repeated legacy entry."""
    win, market, feats = _setup(6)
    t = win.start_ms + 4 * HOUR
    h4 = Counting("h4", [], {t: long_signal(t, 0.5)})
    h1 = Counting("h1", [], {t: long_signal(t, 0.5)})
    clock = WindowEventClock("BTCUSDT", (Timeframe.H1, Timeframe.H4), win.start_ms, win.end_ms)
    res = _bt(win, market, feats).run(clock, {Timeframe.H4: h4, Timeframe.H1: h1})
    assert res.signal_counts["entry"] == 2
    rejected = [o for o in res.orders if o.status == OrderStatus.REJECTED]
    assert [(o.order_id, o.reason) for o in rejected] == [(2, "position_open")]
    assert len(res.trades) == 1 and res.fills[0].order_id == 1


def test_a_finer_provider_sees_the_position_opened_by_a_coarser_one():
    win, market, feats = _setup(6)
    t = win.start_ms + HOUR
    seen: list = []

    class Watcher(Counting):
        def decide(self, ctx):
            seen.append((ctx.now_ms, ctx.portfolio.side, ctx.portfolio.order_pending))
            return None

    h1 = Counting("h1", [], {t: long_signal(t, 0.5)})
    clock = WindowEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1), win.start_ms, win.end_ms)
    _bt(win, market, feats).run(clock, {Timeframe.H1: h1, Timeframe.M15: Watcher("m15", [])})
    by_t = {x[0]: x[1:] for x in seen}
    assert by_t[t] == (0, True)  # same instant, after the 1h entry: pending, not yet filled
    assert by_t[t + MIN15] == (1, False)  # filled at the next 1m open (latency 0), long from then on


# --- causality ------------------------------------------------------------------------------------------


def test_feature_view_is_bound_to_the_event_time_and_refuses_the_future():
    win, market, feats = _setup(3)

    class Peeker(Counting):
        def decide(self, ctx):
            assert ctx.features.value("feat_ready", ctx.now_ms) == 1.0
            ctx.features.value("feat_ready", ctx.now_ms + HOUR)

    clock = WindowEventClock("BTCUSDT", (Timeframe.H1,), win.start_ms, win.end_ms)
    with pytest.raises(LookAheadError):
        _bt(win, market, feats).run(clock, {Timeframe.H1: Peeker("p", [])})


def test_a_15m_provider_cannot_read_the_hourly_row_that_closes_after_it():
    win, market, feats = _setup(3)
    got: list = []

    class Reader(Counting):
        def decide(self, ctx):
            last_hour = ctx.now_ms - ctx.now_ms % HOUR
            got.append(ctx.features.value("feat_ready", last_hour))
            if ctx.now_ms % HOUR:
                with pytest.raises(LookAheadError):
                    ctx.features.value("feat_ready", last_hour + HOUR)
            return None

    clock = WindowEventClock("BTCUSDT", (Timeframe.M15,), win.start_ms, win.end_ms)
    _bt(win, market, feats).run(clock, {Timeframe.M15: Reader("r", [])})
    assert len(got) == 12


def test_a_signal_with_the_wrong_time_is_refused():
    win, market, feats = _setup(3)
    bad = {win.start_ms: long_signal(win.start_ms + HOUR, 0.5)}
    with pytest.raises(SignalError):
        _bt(win, market, feats).run(WindowEventClock("BTCUSDT", (Timeframe.H1,), win.start_ms, win.end_ms), {Timeframe.H1: Scripted(bad)})


# --- clock validation -------------------------------------------------------------------------------


def test_a_clock_shifted_by_one_bar_is_refused_not_silently_accepted():
    """``SimulatedEventClock(start, end)`` emits closes ``start+1h .. end``; the legacy grid's decisions are
    ``start .. end-1h``. The loop refuses the mismatch instead of producing an hour-shifted backtest."""
    win, market, feats = _setup(3)
    with pytest.raises(DataError):
        _bt(win, market, feats).run(SimulatedEventClock("BTCUSDT", (Timeframe.H1,), win.start_ms, win.end_ms), {Timeframe.H1: Scripted({})})


class _ListClock:
    def __init__(self, events):
        self._events, self._i = list(events), -1

    @property
    def now_ms(self) -> int:
        return self._events[self._i].close_ms

    def advance(self):
        if self._i + 1 >= len(self._events):
            return None
        self._i += 1
        return self._events[self._i]


def _ev(close_ms: int, tf: Timeframe = Timeframe.H1) -> BarCloseEvent:
    return BarCloseEvent("BTCUSDT", tf, close_ms - tf.ms, close_ms, close_ms)


def test_a_clock_going_backwards_is_refused():
    win, market, feats = _setup(3)
    s = win.start_ms
    with pytest.raises(DataError, match="backwards"):
        _bt(win, market, feats).run(_ListClock([_ev(s), _ev(s + HOUR), _ev(s)]), {Timeframe.H1: Scripted({})})


def test_an_event_outside_the_window_is_refused_even_for_an_unregistered_timeframe():
    win, market, feats = _setup(3)
    s = win.start_ms
    events = [_ev(s), _ev(s + HOUR), _ev(s + 2 * HOUR), _ev(win.end_ms, Timeframe.M15)]
    with pytest.raises(DataError, match="outside the window"):
        _bt(win, market, feats).run(_ListClock(events), {Timeframe.H1: Scripted({})})


def test_a_clock_that_skips_a_decision_time_is_refused():
    win, market, feats = _setup(3)
    s = win.start_ms
    with pytest.raises(DataError):
        _bt(win, market, feats).run(_ListClock([_ev(s), _ev(s + 2 * HOUR)]), {Timeframe.H1: Scripted({})})


def test_a_clock_that_stops_early_is_refused():
    win, market, feats = _setup(3)
    s = win.start_ms
    with pytest.raises(DataError, match="every decision time"):
        _bt(win, market, feats).run(_ListClock([_ev(s), _ev(s + HOUR)]), {Timeframe.H1: Scripted({})})


def test_an_empty_clock_is_refused_when_a_provider_expects_decisions():
    win, market, feats = _setup(3)
    with pytest.raises(DataError):
        _bt(win, market, feats).run(_ListClock([]), {Timeframe.H1: Scripted({})})


# --- configuration / constructor validation (mirrors Backtester) ------------------------------------


def test_no_providers_is_refused():
    win, market, feats = _setup(3)
    with pytest.raises(ConfigurationError):
        _bt(win, market, feats).run(WindowEventClock("BTCUSDT", (Timeframe.H1,), win.start_ms, win.end_ms), {})


def test_one_provider_object_under_two_timeframes_is_refused():
    win, market, feats = _setup(3)
    p = Scripted({})
    with pytest.raises(ConfigurationError):
        _bt(win, market, feats).run(WindowEventClock("BTCUSDT", (Timeframe.H1, Timeframe.M15), win.start_ms, win.end_ms), {Timeframe.H1: p, Timeframe.M15: p})


def test_constructor_rejects_the_same_inputs_as_the_legacy_backtester():
    win, market, feats = _setup(3)
    other = window(4)
    for args in ((other, market, features_for(other)), (win, market, features_for(other))):
        with pytest.raises(DataError):
            Backtester(app_config(), bt_config(), *args)
        with pytest.raises(DataError):
            EventBacktester(app_config(), bt_config(), *args)


# --- helpers ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("hours", [1, 5, 24])
def test_hourly_timeframe_grid_is_the_legacy_decision_grid(hours):
    win = window(hours)
    assert list(timeframe_grid(win.start_ms, win.end_ms, Timeframe.H1)) == list(decision_grid(win))


def test_window_event_clock_emits_exactly_the_closes_inside_the_window():
    win = window(8)
    clock = WindowEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1, Timeframe.H4), win.start_ms, win.end_ms)
    assert not clock.started
    with pytest.raises(RuntimeError):
        _ = clock.now_ms
    evs = clock.events
    assert all(win.start_ms <= e.close_ms < win.end_ms for e in evs)
    for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4):
        assert [e.close_ms for e in evs if e.timeframe == tf] == list(timeframe_grid(win.start_ms, win.end_ms, tf))
    first = clock.advance()
    assert first.close_ms == win.start_ms and first.timeframe == Timeframe.H4 and clock.now_ms == win.start_ms
    while clock.advance() is not None:
        pass
    assert clock.now_ms == evs[-1].close_ms


def test_window_event_clock_validation():
    with pytest.raises(ValueError):
        WindowEventClock("BTCUSDT", (), 0, HOUR)
    with pytest.raises(ValueError):
        WindowEventClock("BTCUSDT", (Timeframe.H1,), HOUR, HOUR)
