"""Phase 3 gate (`docs/ARVEN_MASTER_PROMPT.md`): the event-driven backtest loop, driven by a clock that
carries only ``Timeframe.H1`` and with the real ``Stage5Pipeline`` registered under ``H1``, must reproduce
the legacy ``Backtester.run`` result byte for byte - the same ``report.result_hash`` over the meta, orders,
fills, funding, trades and equity ledgers.

Same fixture pattern as ``tests/pipeline/test_stage5_no_ml_regression.py`` (relative equality of two runs on
identical synthetic fixtures; no hard-coded hash). Every pipeline seed below was checked to produce real
trades (entries, stop / take-profit exits, funding while in a position, and for some an END_OF_PERIOD
close), and the test asserts that, so the proof exercises order submission, fills, costs and funding, not
an empty equity curve.
"""

from __future__ import annotations

import pytest
from bt_helpers import (
    HOUR,
    Scripted,
    app_config,
    bt_config,
    features_for,
    long_signal,
    make_market,
    short_signal,
    window,
    zero_cost_app,
)
from pipeline_helpers import make_feature_data, make_pipeline, random_1m_market

from arven.backtest.engine import Backtester
from arven.backtest.event_engine import EventBacktester, WindowEventClock
from arven.backtest.report import result_hash, result_tables
from arven.core.signal import Signal
from arven.core.timeframes import Timeframe
from arven.core.types import Action
from arven.engine.clock import SimulatedEventClock

DAYS = 180
TRADING_SEEDS = [0, 5, 9, 17, 22]


def _h1_clock(win) -> SimulatedEventClock:
    """A plain Phase 1 SimulatedEventClock over the window's hourly decision times (closes at
    ``start_ms .. end_ms - 1h``, i.e. bars opening one hour earlier)."""
    return SimulatedEventClock("BTCUSDT", (Timeframe.H1,), win.start_ms - HOUR, win.end_ms - HOUR)


def _fixtures(seed: int, days: int = DAYS):
    feats = make_feature_data(days, seed)
    market = random_1m_market(days * 24, seed=seed + 1000)
    return feats, market, window(days * 24)


def _both(app, feats, market, win, *, stress=False, clock=None):
    legacy = Backtester(app, bt_config(), win, market, feats, stress=stress).run(make_pipeline())
    event = EventBacktester(app, bt_config(), win, market, feats, stress=stress).run(
        clock or _h1_clock(win), {Timeframe.H1: make_pipeline()}
    )
    return legacy, event


def _assert_identical(a, b):
    assert result_tables(a) == result_tables(b)  # table-by-table first: a precise diff on failure
    assert result_hash(a) == result_hash(b)


@pytest.mark.parametrize("seed", TRADING_SEEDS)
def test_stage5_pipeline_result_hash_is_identical_with_real_costs(seed):
    feats, market, win = _fixtures(seed)
    legacy, event = _both(app_config(), feats, market, win)
    assert len(legacy.trades) > 0 and len(legacy.fills) == 2 * len(legacy.trades)
    assert legacy.signal_counts["entry"] > 0
    assert any(t.fees > 0 for t in legacy.trades)  # real fee/slippage model in play
    _assert_identical(legacy, event)


@pytest.mark.parametrize("seed", TRADING_SEEDS)
def test_stage5_pipeline_result_hash_is_identical_with_zero_costs(seed):
    feats, market, win = _fixtures(seed)
    legacy, event = _both(zero_cost_app(), feats, market, win)
    assert len(legacy.trades) > 0
    _assert_identical(legacy, event)


@pytest.mark.parametrize("seed", [0, 22])
def test_stage5_pipeline_result_hash_is_identical_under_cost_stress(seed):
    feats, market, win = _fixtures(seed)
    legacy, event = _both(app_config(), feats, market, win, stress=True)
    assert len(legacy.trades) > 0 and legacy.stress and event.stress
    _assert_identical(legacy, event)


def test_the_proof_seeds_cover_funding_and_end_of_period_exits():
    """Non-vacuity of the seed set as a whole: funding settlements while in a position and a forced
    end-of-window close both occur somewhere in it (so both code paths are inside the equivalence proof)."""
    funding = end_of_period = 0
    for seed in TRADING_SEEDS:
        feats, market, win = _fixtures(seed)
        res = Backtester(app_config(), bt_config(), win, market, feats).run(make_pipeline())
        funding += len(res.funding)
        end_of_period += sum(t.exit_reason.value == "END_OF_PERIOD" for t in res.trades)
    assert funding > 0 and end_of_period > 0


@pytest.mark.parametrize("seed", [0, 9])
def test_window_event_clock_gives_the_same_result(seed):
    feats, market, win = _fixtures(seed)
    legacy, event = _both(app_config(), feats, market, win, clock=WindowEventClock("BTCUSDT", (Timeframe.H1,), win.start_ms, win.end_ms))
    _assert_identical(legacy, event)


@pytest.mark.parametrize("seed", [0, 17])
def test_unused_timeframes_on_the_clock_do_not_change_the_result(seed):
    """Events of timeframes nobody is registered on are skipped entirely (no simulation call), so a clock
    that also carries 4h and 15m events still yields the legacy 1h result exactly."""
    feats, market, win = _fixtures(seed)
    clock = WindowEventClock("BTCUSDT", (Timeframe.M15, Timeframe.H1, Timeframe.H4), win.start_ms, win.end_ms)
    legacy, event = _both(app_config(), feats, market, win, clock=clock)
    assert len(legacy.trades) > 0
    _assert_identical(legacy, event)


def test_an_all_no_trade_run_is_also_identical():
    feats, market, win = _fixtures(1, days=150)  # too short to leave the warm-up: every decision is None
    legacy, event = _both(app_config(), feats, market, win)
    assert legacy.trades == () and legacy.signal_counts["none"] == legacy.n_decisions
    _assert_identical(legacy, event)


def test_scripted_provider_covering_every_order_path_is_identical():
    """Hand-made market + scripted signals hitting every branch of the signal -> order handling: entry, a
    rejected second entry (position_open), close, close while flat (close_ignored), plain NO_TRADE, a leverage
    cap rejection, a time stop, a stop-loss, and funding while in a position."""
    hours = 48
    t0 = window(hours).start_ms
    bars = {
        5 * 60 + 30: (30_000.0, 30_000.0, 28_000.0, 28_500.0),  # a -6.7% wick: stops out the hour-1 long
        30 * 60 + 10: (28_500.0, 31_000.0, 28_500.0, 30_500.0),  # +8.8% wick: take-profit for the hour-25 long
    }
    market = make_market(hours, bars, funding_rates={t0 + k * 8 * HOUR: 1e-4 * (k + 1) for k in range(8)})
    t = lambda h: t0 + h * HOUR  # noqa: E731
    signals = {
        t(1): long_signal(t(1), 0.5, stop_pct=0.05),
        t(2): short_signal(t(2), 0.5),  # rejected: position open
        t(3): Signal(t(3), Action.NO_TRADE),
        t(6): long_signal(t(6), 0.5),  # after the hour-1 long was stopped out
        t(8): Signal(t(8), Action.NO_TRADE, close_position=True),  # closes the hour-6 long
        t(9): Signal(t(9), Action.NO_TRADE, close_position=True),  # close_ignored: flat
        t(10): short_signal(t(10), 99.0),  # exceeds the leverage cap
        t(12): short_signal(t(12), 1.0, max_holding_minutes=600),  # time stop
        t(25): long_signal(t(25), 1.0, stop_pct=0.02, take_profit_pct=0.03),
    }
    win = window(hours)
    feats = features_for(win)
    legacy = Backtester(app_config(), bt_config(), win, market, feats).run(Scripted(signals))
    event = EventBacktester(app_config(), bt_config(), win, market, feats).run(_h1_clock(win), {Timeframe.H1: Scripted(signals)})
    counts = legacy.signal_counts
    assert counts["entry"] >= 4 and counts["close"] >= 1 and counts["close_ignored"] >= 1 and counts["no_trade"] >= 1
    reasons = {o.reason for o in legacy.orders}
    assert {"position_open", "exceeds_leverage_cap"} <= reasons
    assert [x.exit_reason.value for x in legacy.trades] == ["STOP", "SIGNAL_CLOSE", "TIME_STOP", "TAKE_PROFIT"]
    assert len(legacy.funding) > 0
    _assert_identical(legacy, event)
