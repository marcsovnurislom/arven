"""Phase 4 gate: hand-built 1m-bar scenarios resolving an EngineSignal's TP ladder/stop."""

from __future__ import annotations

import pytest
from bt_helpers import T0, app_config, flat_bar, make_market, zero_cost_app

from arven.backtest.errors import DataError
from arven.backtest.paper_tracker import track_signal
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, tp_ladder_from_r_multiples
from arven.engine.signal_events import SignalUpdateKind

MIN = 60_000


def make_signal(side=1, entry=100.0, stop=98.0, ladder=((1.0, 0.5), (2.0, 0.3), (3.0, 0.2)), **kw):
    tp = tp_ladder_from_r_multiples(ladder, entry=entry, stop=stop, side=side)
    defaults = dict(
        symbol="BTCUSDT", side=side, strategy_id="s4", strategy_version="v1", grade=Grade.EXPERIMENTAL,
        event_time_ms=0, entry_reference=entry, stop=stop, tp_ladder=tp, risk_fraction=0.01,
        confidence=0.7, regime="TREND_UP/NORMAL", reasons=("x",), risk_checks=("ok",),
        versions=SignalVersions("v1", "hash", "abc123"),
    )
    defaults.update(kw)
    return EngineSignal(**defaults)


def test_three_rungs_fill_on_three_separate_bars_with_zero_costs():
    bars = {0: flat_bar(100.0), 1: (100.0, 102.5, 100.0, 102.0), 5: (102.0, 104.5, 102.0, 104.0), 10: (104.0, 106.5, 104.0, 106.0)}
    market = make_market(2, bars, base_price=100.0, start_ms=T0)
    signal = make_signal()
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs)
    assert result.resolution is not None
    res = result.resolution
    assert [leg.exit_reason for leg in res.legs] == ["TP1", "TP2", "TP3"]
    assert res.fully_closed
    assert res.r_multiple == pytest.approx(0.5 * 1 + 0.3 * 2 + 0.2 * 3)  # 1.7, before fees (zero here)
    kinds = [u.kind for u in result.updates]
    assert kinds == [SignalUpdateKind.TP_HIT, SignalUpdateKind.TP_HIT, SignalUpdateKind.TP_HIT]


def test_stop_beats_take_profit_in_the_same_bar():
    # bar 1's range touches both the stop (98) and TP1 (102) - the documented tie rule says STOP wins.
    bars = {0: flat_bar(100.0), 1: (100.0, 103.0, 97.0, 100.0)}
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal()
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs)
    res = result.resolution
    assert len(res.legs) == 1 and res.legs[0].exit_reason == "STOP"
    assert res.fully_closed
    assert res.r_multiple == pytest.approx(-1.0)


def test_only_one_rung_resolves_per_bar_even_if_the_range_reaches_two():
    # bar 1 gaps straight through both TP1 (102) and TP2 (104) in one bar - only TP1 is credited that bar;
    # TP2 must wait for a later bar (here, bar 2) even though it was technically already reached.
    bars = {0: flat_bar(100.0), 1: (100.0, 105.0, 100.0, 105.0), 2: (105.0, 105.0, 105.0, 105.0)}
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal()
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs)
    res = result.resolution
    assert [leg.exit_reason for leg in res.legs] == ["TP1", "TP2"]
    assert result.updates[0].time_ms == T0 + 1 * MIN
    assert result.updates[1].time_ms == T0 + 2 * MIN  # TP2 waited one extra bar


def test_time_stop_closes_the_remainder_at_the_bar_open():
    bars = {0: flat_bar(100.0)}  # nothing ever touches stop or any TP
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal(max_holding_minutes=3)
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs)
    res = result.resolution
    assert res.legs[0].exit_reason == "TIME_STOP" and res.fully_closed
    assert result.updates[-1].kind == SignalUpdateKind.CLOSED
    assert result.updates[-1].time_ms == T0 + 3 * MIN


def test_stop_moved_to_breakeven_after_first_tp_then_closes_flat():
    # TP1 fills at minute 1 (50%); stop for the remaining 50% moves to entry (100); a later bar touches 100
    # (not the original 98) and the remainder closes flat.
    bars = {0: flat_bar(100.0), 1: (100.0, 102.5, 100.0, 102.0), 5: (102.0, 103.0, 99.5, 100.0)}
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal()
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs, move_stop_to_breakeven_after_first_tp=True)
    res = result.resolution
    assert [leg.exit_reason for leg in res.legs] == ["TP1", "STOP_BREAKEVEN"]
    assert res.legs[1].exit_price == pytest.approx(100.0)
    assert any(u.kind == SignalUpdateKind.STOP_MOVED for u in result.updates)
    # gross = 0.5*1R (TP1) + 0.5*0R (breakeven) = 0.5R
    assert res.r_multiple == pytest.approx(0.5)


def test_without_breakeven_the_original_stop_still_applies_after_a_partial_tp():
    bars = {0: flat_bar(100.0), 1: (100.0, 102.5, 100.0, 102.0), 5: (102.0, 103.0, 97.5, 100.0)}
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal()
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs, move_stop_to_breakeven_after_first_tp=False)
    res = result.resolution
    assert [leg.exit_reason for leg in res.legs] == ["TP1", "STOP"]
    assert res.legs[1].exit_price == pytest.approx(98.0)


def test_real_costs_make_every_leg_fee_positive_and_exit_price_worse_than_planned():
    bars = {0: flat_bar(100.0), 1: (100.0, 102.5, 100.0, 102.0)}
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal(ladder=((1.0, 1.0),))
    result = track_signal(signal, T0, 100.0, market, app_config().costs)
    leg = result.resolution.legs[0]
    assert leg.fee > 0.0
    assert leg.exit_price < 102.0  # a long's exit is worse (lower) than the planned level after slippage
    assert result.resolution.r_multiple < 1.0  # costs eat into the planned 1R


def test_short_side_resolves_symmetrically():
    bars = {0: flat_bar(100.0), 1: (100.0, 100.0, 97.5, 98.0)}
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal(side=-1, entry=100.0, stop=102.0, ladder=((1.0, 1.0),))
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs)
    res = result.resolution
    assert res.legs[0].exit_reason == "TP1"
    assert res.r_multiple == pytest.approx(1.0)


def test_entry_time_not_in_the_market_data_raises():
    market = make_market(1, {}, base_price=100.0, start_ms=T0)
    signal = make_signal()
    with pytest.raises(DataError):
        track_signal(signal, T0 + 30_000, 100.0, market, zero_cost_app().costs)  # not a 1m bar boundary


def test_nothing_touched_within_the_given_data_returns_no_resolution():
    bars = {0: flat_bar(100.0)}  # flat forever within this short window, never reaches stop or any TP
    market = make_market(1, bars, base_price=100.0, start_ms=T0)
    signal = make_signal()  # no max_holding_minutes
    result = track_signal(signal, T0, 100.0, market, zero_cost_app().costs)
    assert result.resolution is None
    assert result.updates == ()
