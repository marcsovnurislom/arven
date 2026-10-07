"""Phase 2: ``MultiTFView`` as-of selection, the three documented outcomes (raise / stale / fresh), and the
same-instant (coarsest-first) visibility rule."""

from __future__ import annotations

import math

import numpy as np
import pytest
from synthetic_market import START_MS, aggregate, make_5m

from arven.core.series import BarSeries
from arven.core.timeframes import Timeframe
from arven.engine.clock import SimulatedEventClock
from arven.engine.errors import LookAheadError
from arven.engine.events import BarCloseEvent
from arven.engine.features import TFFeatureParams, compute_tf_features
from arven.engine.multitf import MultiTFView
from arven.engine.spec import StrategySpec

HOUR = 3_600_000
H1, H4, M15 = Timeframe.H1, Timeframe.H4, Timeframe.M15
SMALL = TFFeatureParams(ema_fast=2, ema_slow=3, slope_bars=1, adx_period=2, atr_period=2, warmup_factor=1.0)
SPEC = StrategySpec("t", "1", context_tfs=(H4,), setup_tf=H1, trigger_tf=M15, warmup_bars=1)
LEGACY = StrategySpec("legacy", "1", context_tfs=(H4,), setup_tf=H1, trigger_tf=H1, warmup_bars=1)


def market(days=6, delay_ms=0, seed=2):
    five = make_5m(288 * days, seed=seed)
    return {tf: aggregate(five, tf, delay_ms) for tf in (M15, H1, H4)}


def view(bars, params=SMALL):
    return MultiTFView.from_bars(bars, bars.keys(), params)


def drop_last(s: BarSeries, k: int) -> BarSeries:
    return s.available_until(int(s.available_at_ms[-1 - k]))


# --- the "no row at all" case raises -----------------------------------------------------------------


def test_before_the_first_bar_closes_the_view_raises():
    v = view(market())
    with pytest.raises(LookAheadError):
        v.row_at(H1, START_MS + HOUR - 1)
    with pytest.raises(LookAheadError):
        v.at(START_MS + HOUR, SPEC)  # 15m and 1h exist, but no 4h bar has closed yet


def test_an_empty_table_raises():
    bars = market()
    bars[H4] = bars[H4].available_until(START_MS)  # no 4h bar at all
    v = view(bars)
    assert len(v.table(H4)) == 0
    with pytest.raises(LookAheadError):
        v.row_at(H4, START_MS + 100 * HOUR)


def test_lookahead_error_is_not_the_legacy_backtest_class():
    from arven.backtest.errors import LookAheadError as Legacy

    assert not issubclass(LookAheadError, Legacy)


# --- exact as-of boundary (no off-by-one) ---------------------------------------------------------------


def test_a_bar_becomes_visible_exactly_at_its_close_not_one_ms_earlier():
    v = view(market())
    close = START_MS + 5 * HOUR
    assert v.row_at(H1, close - 1).close_ms == close - HOUR
    assert v.row_at(H1, close).close_ms == close
    assert v.row_at(H1, close + HOUR - 1).close_ms == close


def test_with_a_delay_the_bar_becomes_visible_only_at_close_plus_delay():
    v = view(market(delay_ms=60_000))
    close = START_MS + 5 * HOUR
    assert v.row_at(H1, close).close_ms == close - HOUR
    assert v.row_at(H1, close + 59_999).close_ms == close - HOUR
    row = v.row_at(H1, close + 60_000)
    assert row.close_ms == close and row.available_at_ms == close + 60_000 and not row.stale


def test_same_instant_coarser_close_is_visible_to_the_finer_trigger():
    """Phase 1 tie rule: at 08:00 the 4h bar 04:00-08:00 has closed and must be the context row."""
    v = view(market())
    clock = SimulatedEventClock("BTCUSDT", (M15, H1, H4), START_MS, START_MS + 12 * HOUR)
    at_8 = [e for e in clock.events if e.close_ms == START_MS + 8 * HOUR]
    assert [e.timeframe for e in at_8] == [H4, H1, M15]  # coarsest first ...
    for spec, ev in ((SPEC, at_8[2]), (LEGACY, at_8[1])):
        snap = v.for_event(ev, spec)
        assert snap.row(H4).close_ms == START_MS + 8 * HOUR  # ... and visible, not the 00:00-04:00 bar
        assert snap.row(H1).close_ms == START_MS + 8 * HOUR
        assert snap.trigger.close_ms == ev.close_ms
    # one 15m bar earlier the 4h context is still the previous bar
    snap = v.at(START_MS + 8 * HOUR - Timeframe.M15.ms, SPEC)
    assert snap.row(H4).close_ms == START_MS + 4 * HOUR


def test_for_event_with_delay_uses_the_events_available_at():
    bars = market(delay_ms=30_000)
    v = view(bars)
    clock = SimulatedEventClock("BTCUSDT", (M15, H4), START_MS, START_MS + 12 * HOUR, delay_ms=30_000)
    ev = [e for e in clock.events if e.timeframe == M15 and e.close_ms == START_MS + 8 * HOUR][0]
    snap = v.for_event(ev, SPEC)
    assert snap.t_ms == ev.available_at_ms == START_MS + 8 * HOUR + 30_000
    assert snap.trigger.close_ms == ev.close_ms and not snap.trigger.stale
    assert snap.row(H4).close_ms == START_MS + 8 * HOUR


def test_for_event_rejects_an_event_of_another_timeframe():
    v = view(market())
    ev = BarCloseEvent("BTCUSDT", H1, START_MS + 4 * HOUR, START_MS + 5 * HOUR, START_MS + 5 * HOUR)
    with pytest.raises(ValueError):
        v.for_event(ev, SPEC)


# --- the stale case: NaN, never carried forward ---------------------------------------------------------


def test_row_older_than_one_bar_is_stale_and_all_nan():
    bars = market()
    bars[H4] = drop_last(bars[H4], 3)  # the 4h feed stops 3 bars early
    v = view(bars)
    last = v.table(H4)
    last_avail = int(last.available_at_ms[-1])
    fresh = v.row_at(H4, last_avail + 4 * HOUR - 1)
    assert not fresh.stale and np.isfinite(fresh["close"])
    stale = v.row_at(H4, last_avail + 4 * HOUR)
    assert stale.stale and stale.close_ms == int(last.close_ms[-1])
    assert all(math.isnan(x) for x in stale.values.values())


def test_missing_trigger_bar_at_the_end_of_data_makes_the_trigger_row_stale():
    bars = market()
    bars[M15] = drop_last(bars[M15], 1)
    v = view(bars)
    end = int(bars[H1].close_time_ms[-1])
    ev = BarCloseEvent("BTCUSDT", M15, end - Timeframe.M15.ms, end, end)
    snap = v.for_event(ev, SPEC)
    assert snap.trigger.close_ms == end - Timeframe.M15.ms  # the previous bar ...
    assert snap.trigger.stale and math.isnan(snap.trigger["close"])  # ... and therefore unusable
    assert not snap.setup.stale


# --- the defined-NaN case: warm-up / gaps return a row, never raise ---------------------------------


def test_warmup_nan_is_a_row_not_an_error():
    v = view(market())
    row = v.row_at(H1, START_MS + HOUR)  # first 1h bar: indicators still warming up
    assert row.bars_seen == 1 and not row.stale and row.complete
    assert np.isfinite(row["close"]) and math.isnan(row["atr_2"]) and math.isnan(row["adx_2"])


def test_missing_bar_inside_the_data_is_a_complete_false_nan_row():
    bars = market()
    s = bars[H1]
    keep = np.ones(len(s), dtype=bool)
    keep[10] = False
    bars[H1] = BarSeries(
        H1, 0, s.open_time_ms[keep], s.open[keep], s.high[keep], s.low[keep], s.close[keep], s.volume[keep],
        s.trade_count[keep], s.taker_buy_volume[keep], s.complete[keep],
    )
    v = view(bars)
    row = v.row_at(H1, int(s.close_time_ms[10]))
    assert row.close_ms == int(s.close_time_ms[10]) and not row.complete and not row.stale
    assert all(math.isnan(x) for x in row.values.values())


# --- contents ------------------------------------------------------------------------------------------


def test_row_values_equal_the_table_row_and_bars_seen_counts_from_one():
    bars = market()
    v = view(bars)
    table = compute_tf_features(bars[H1], SMALL)
    i = 30
    row = v.row_at(H1, int(table.close_ms[i]))
    assert row.bars_seen == i + 1
    assert row.open_ms == int(table.open_ms[i]) and row.available_at_ms == int(table.available_at_ms[i])
    assert dict(row.values) == {n: float(x) for n, x in zip(table.names, table.values[i], strict=True)}
    with pytest.raises(TypeError):
        row.values["close"] = 0.0  # read-only


def test_snapshot_roles_and_context_order():
    v = view(market())
    spec = StrategySpec("x", "1", context_tfs=(H4, H1), setup_tf=H1, trigger_tf=M15, warmup_bars=1)
    snap = v.at(START_MS + 24 * HOUR, spec)
    assert snap.trigger.timeframe == M15 and snap.setup.timeframe == H1
    assert [r.timeframe for r in snap.context] == [H4, H1]
    assert snap.row(H1) == snap.setup
    with pytest.raises(KeyError):
        snap.row(Timeframe.M5)


def test_unknown_timeframe_and_mismatched_table_are_configuration_errors():
    bars = market()
    v = view({H1: bars[H1]})
    with pytest.raises(KeyError):
        v.row_at(H4, START_MS + 24 * HOUR)
    with pytest.raises(KeyError):
        v.at(START_MS + 24 * HOUR, SPEC)
    with pytest.raises(ValueError):
        MultiTFView({H4: compute_tf_features(bars[H1], SMALL)})


def test_from_bars_builds_only_the_requested_timeframes():
    v = MultiTFView.from_bars(market(), (H1, H4, H1), SMALL)
    assert v.timeframes == (H1, H4)
