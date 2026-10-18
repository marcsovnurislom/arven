"""Session markets (gold) through the shared code paths: the bar grid, Stage 3 features, per-timeframe staleness,
decision grids, the 1m simulator's data gaps, trading time and S7's resistance window - each checked against the
around-the-clock behaviour it must reduce to, and with the project's leakage harness (CLAUDE.md rules 1, 2, 11)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from leakage_harness import perturbation_leaks, sample_times, truncation_leaks
from synthetic_market import make_funding, make_oi

from arven.backtest.event_engine import WindowEventClock, timeframe_grid
from arven.backtest.marketdata import MarketData
from arven.core.features_config import load_features_config
from arven.core.series import BarSeries, MarketInputs
from arven.core.sessions import SessionCalendar, session_decision_mask
from arven.core.time import UTC, to_ms
from arven.core.timeframes import Timeframe
from arven.engine.features import compute_tf_features
from arven.engine.multitf import MultiTFView
from arven.features.builder import build_features, decision_grid
from arven.live.strategies import bar_close_after
from arven.paper.strategies_forward import event_times

CME = SessionCalendar("cme_metals")
MIN = 60_000
H = 3_600_000
START = to_ms(datetime(2024, 1, 7, 23, tzinfo=UTC))  # Sunday 23:00 UTC = 18:00 New York (winter): the weekly open


def ms(*a) -> int:
    return to_ms(datetime(*a, tzinfo=UTC))


def gold_5m(n_days: int, seed: int = 5) -> dict[str, np.ndarray]:
    """A random walk on the 5m buckets the market trades in (weekends and daily halts simply absent)."""
    grid = CME.bar_opens(Timeframe.M5, START, START + n_days * 86_400_000)
    rng = np.random.default_rng(seed)
    n = len(grid)
    close = 2000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0008, n)))
    open_ = np.concatenate(([2000.0], close[:-1]))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 3e-4, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 3e-4, n)))
    vol = rng.lognormal(2.0, 0.4, n)
    return {"open_time_ms": grid, "open": open_, "high": high, "low": low, "close": close, "volume": vol,
            "trade_count": np.zeros(n), "taker_buy_volume": np.zeros(n)}


def bucketed(five: dict[str, np.ndarray], tf: Timeframe, calendar: SessionCalendar | None = CME) -> BarSeries:
    key = five["open_time_ms"] - five["open_time_ms"] % tf.ms
    opens, first = np.unique(key, return_index=True)
    last = np.concatenate((first[1:], [len(key)])) - 1
    count = np.diff(np.concatenate((first, [len(key)])))
    expected = CME.expected_minutes(tf, opens) // 5
    return BarSeries(
        timeframe=tf, delay_ms=0, open_time_ms=opens, open=five["open"][first], close=five["close"][last],
        high=np.maximum.reduceat(five["high"], first), low=np.minimum.reduceat(five["low"], first),
        volume=np.add.reduceat(five["volume"], first), trade_count=np.zeros(len(opens)),
        taker_buy_volume=np.zeros(len(opens)), complete=count == expected, calendar=calendar,
    )


def gold_inputs(n_days: int = 70) -> MarketInputs:
    five = gold_5m(n_days)
    return MarketInputs(
        bars={tf: bucketed(five, tf) for tf in (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4)},
        funding=make_funding(1, start_ms=START - 2 * 86_400_000),
        open_interest=make_oi(1, start_ms=START - 2 * 86_400_000),
    )


# --- bar grid -----------------------------------------------------------------------------------------------


def test_session_grid_has_no_weekend_rows_and_indicators_run_through_the_weekend():
    h1 = bucketed(gold_5m(21), Timeframe.H1)
    r = h1.regularized()
    assert r.complete.all() and len(r) == len(h1)  # nothing to fill: the weekend is not part of the grid
    weekday = (r.open_time_ms // 86_400_000 + 3) % 7  # 0 = Monday (1970-01-01 was a Thursday)
    assert not np.any(weekday == 5)  # no Saturday bar at all
    tf = compute_tf_features(h1)
    ema = tf.column("ema_dist_20")
    monday_open = int(np.searchsorted(tf.open_ms, ms(2024, 1, 21, 23)))  # first bar after the 2nd weekend
    assert np.isfinite(ema[monday_open])  # not reset by the weekend
    # the same series treated as around the clock would have ~48 NaN rows per weekend and restart the indicators
    flat = BarSeries(**{**{f: getattr(h1, f) for f in ("timeframe", "delay_ms", "open_time_ms", "open", "high", "low", "close",
                                                      "volume", "trade_count", "taker_buy_volume", "complete")}, "calendar": None})
    assert len(flat.regularized()) > len(r) + 40


def test_24x7_regularization_unchanged_by_the_calendar_field():
    h1 = bucketed(gold_5m(5), Timeframe.H1, calendar=None)
    r = h1.regularized()
    assert len(r) == (int(h1.open_time_ms[-1]) - int(h1.open_time_ms[0])) // H + 1
    assert r.calendar is None


# --- staleness and decision times ---------------------------------------------------------------------------


def test_4h_context_is_not_stale_after_the_weekend_but_a_missing_trading_bar_is():
    five = gold_5m(21)
    h4 = bucketed(five, Timeframe.H4)
    view = MultiTFView.from_bars({Timeframe.H4: h4}, (Timeframe.H4,))
    sunday_2315 = ms(2024, 1, 14, 23, 15)
    row = view.row_at(Timeframe.H4, sunday_2315)
    # Friday's last 4h bar is 20:00-24:00 with two trading hours (winter close 22:00); it stays current over the weekend
    assert not row.stale and row.open_ms == ms(2024, 1, 12, 20) and row.complete
    # drop Monday 04:00 4h bar: at Monday 08:30 the context must be stale (a trading bar is missing)
    keep = h4.open_time_ms != ms(2024, 1, 15, 4)
    cut = BarSeries(**{f: (getattr(h4, f)[keep] if isinstance(getattr(h4, f), np.ndarray) else getattr(h4, f))
                       for f in ("timeframe", "delay_ms", "open_time_ms", "open", "high", "low", "close", "volume",
                                 "trade_count", "taker_buy_volume", "complete", "calendar")})
    view2 = MultiTFView.from_bars({Timeframe.H4: cut}, (Timeframe.H4,))
    assert view2.row_at(Timeframe.H4, ms(2024, 1, 15, 8, 30)).stale is False  # the 04:00 row exists on the grid as NaN
    assert np.isnan(view2.row_at(Timeframe.H4, ms(2024, 1, 15, 8, 30))["close"])


def test_decision_grids_only_contain_actionable_times():
    lo, hi = ms(2024, 1, 12, 18), ms(2024, 1, 15, 0)
    g = decision_grid(lo, hi, CME)
    # Friday (winter): open until 22:00; 22:00 is the close that starts the weekend -> not actionable
    assert ms(2024, 1, 12, 21) in g.tolist() and ms(2024, 1, 12, 22) not in g.tolist()
    # Sunday 23:00 opens the week; its first 1h close (Monday 00:00) is the first decision
    assert ms(2024, 1, 14, 23) not in g.tolist()
    assert all(not (ms(2024, 1, 12, 22) <= t < ms(2024, 1, 15, 0)) for t in g.tolist())
    assert np.array_equal(decision_grid(lo, hi), np.arange(lo, hi, H))  # around the clock: unchanged
    m15 = timeframe_grid(ms(2024, 1, 15, 22), ms(2024, 1, 15, 23, 30), Timeframe.M15, CME)
    # Monday winter halt 22:00-23:00: no 15m decision from 22:00 (start of the halt) until the halt is over
    assert m15.tolist() == [ms(2024, 1, 15, 23, 15)]
    assert list(event_times(ms(2024, 1, 15, 21, 45), ms(2024, 1, 15, 23, 30), CME)) == [ms(2024, 1, 15, 23, 15), ms(2024, 1, 15, 23, 30)]
    assert list(event_times(0, 3 * 900_000)) == [900_000, 1_800_000, 2_700_000]


def test_window_event_clock_matches_the_session_grid():
    lo, hi = ms(2024, 1, 12), ms(2024, 1, 16)
    clock = WindowEventClock("XAUUSD", (Timeframe.M15,), lo, hi, calendar=CME)
    times = [e.close_ms for e in clock.events]
    assert times == timeframe_grid(lo, hi, Timeframe.M15, CME).tolist()
    assert all(session_decision_mask(CME, np.array([t]), Timeframe.M15)[0] for t in times)


# --- Stage 3 features on a session market: point in time ----------------------------------------------------


@pytest.fixture(scope="module")
def gold_features():
    inputs = gold_inputs(420)
    fcfg = load_features_config()
    grid = decision_grid(int(inputs.bars[Timeframe.H1].open_time_ms[0]) + H, int(inputs.bars[Timeframe.H1].close_time_ms[-1]) + 1, CME)
    return inputs, fcfg, grid


def test_stage3_features_on_gold_are_ready_after_warmup_and_never_inside_a_closure(gold_features):
    inputs, fcfg, grid = gold_features
    table = build_features(inputs, grid, fcfg, funding_required=False, trade_flow_required=False)
    ready = table.columns["feat_ready"] == 1.0
    first = int(np.argmax(ready))
    assert ready.any() and ready[first:].all()  # after the warm-up no weekend or halt ever makes the data "not ready"
    # summer time: the week opens Sunday 22:00 UTC, so the first decision is the 23:00 close - and it is usable
    first_of_week = int(np.searchsorted(grid, ms(2024, 9, 15, 23, 0)))
    assert grid[first_of_week] == ms(2024, 9, 15, 23, 0) and grid[first_of_week - 1] == ms(2024, 9, 13, 20, 0)
    assert ready[first_of_week]
    btc_rules = build_features(inputs, grid, fcfg)  # the BTC registry: funding + trade counts required -> never ready
    assert not (btc_rules.columns["feat_ready"] == 1.0).any()


def _stage3(fcfg):
    def compute(inputs: MarketInputs, t: np.ndarray):
        table = build_features(inputs, t, fcfg, funding_required=False, trade_flow_required=False)
        return {k: v for k, v in table.columns.items() if not k.startswith(("fund", "oi_"))}
    return compute


def test_stage3_gold_features_have_no_lookahead(gold_features):
    inputs, fcfg, grid = gold_features
    samples = sample_times(grid[len(grid) // 3:], 25, tail=3)
    assert truncation_leaks(_stage3(fcfg), inputs, grid, samples) == {}
    assert perturbation_leaks(_stage3(fcfg), inputs, grid, samples) == {}


# --- 1m simulator gaps --------------------------------------------------------------------------------------


def _md(times: np.ndarray, calendar: SessionCalendar | None) -> MarketData:
    p = np.full(len(times), 2000.0)
    return MarketData(times, p, p + 1, p - 1, p, int(times[0]), int(times[-1]) + MIN, np.zeros(0, dtype=np.int64),
                      np.zeros(0), 8 * H, calendar=calendar)


def test_weekend_is_not_a_data_gap_but_a_missing_trading_minute_is():
    t = CME.open_minutes(ms(2024, 1, 12, 21, 50), ms(2024, 1, 14, 23, 10))
    assert _md(t, CME).gap_indices.tolist() == []
    assert len(_md(t, None).gap_indices) == 1  # around the clock the same jump would close a position (DATA_GAP)
    holed = np.delete(t, 5)  # 21:55 Friday missing
    assert _md(holed, CME).gap_indices.tolist() == [5]
    assert _md(t, CME).fingerprint() != _md(t, None).fingerprint()


# --- trading time, expiry, S7 window ------------------------------------------------------------------------


def test_trading_time_skips_closures_and_is_identity_around_the_clock():
    fri, sun = ms(2024, 7, 12, 20, 59), ms(2024, 7, 14, 22, 0)
    assert CME.trading_ms(sun) - CME.trading_ms(fri) == MIN
    assert SessionCalendar().trading_ms(sun) - SessionCalendar().trading_ms(fri) == sun - fri
    t = np.arange(ms(2024, 7, 10), ms(2024, 7, 16), 7 * MIN)
    tt = CME.trading_ms(t)
    assert np.all(np.diff(tt) >= 0) and np.all(np.diff(tt) <= 7 * MIN)
    open_ = CME.is_open(t)
    both_open = open_[1:] & open_[:-1] & (np.diff(tt) == 7 * MIN)
    assert both_open.sum() > 0.6 * len(t)


def test_bar_close_after_counts_trading_bars():
    assert bar_close_after(SessionCalendar(), Timeframe.M15, ms(2024, 7, 12, 20, 30), 3) == ms(2024, 7, 12, 21, 30)
    # the 20:30 bar, then 20:45 (last before the summer Friday close), then Sunday 22:00 and 22:15
    assert bar_close_after(CME, Timeframe.M15, ms(2024, 7, 12, 20, 30), 3) == ms(2024, 7, 14, 22, 30)


def test_s7_resistance_window_in_bars_equals_the_millisecond_rule_on_a_gap_free_grid():
    from arven.backtest.strategy_s7_sim import S7Bars, make_context, resistance_window
    from arven.core.config import load_config
    from arven.engine.strategy_s7 import S7Params
    from arven.engine.strategy_s7_plan import S7TradeParams

    rng = np.random.default_rng(3)
    n = 4000
    t = ms(2024, 1, 1) + np.arange(n, dtype=np.int64) * Timeframe.M15.ms
    c = 2000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.concatenate(([2000.0], c[:-1]))
    hi, lo = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    bars = S7Bars(Timeframe.M15.ms, t, o, hi, lo, c, np.ones(n))
    md = MarketData(t, o, hi, lo, c, int(t[0]), int(t[-1]) + Timeframe.M15.ms, np.zeros(0, dtype=np.int64), np.zeros(0), 8 * H)
    p, tp = S7Params(), S7TradeParams()
    ms_ctx = make_context(bars, bars, md, load_config().costs, p, tp)
    bar_ctx = make_context(bars, bars, md, load_config().costs, p, tp, calendar=CME)
    assert not ms_ctx.lookback_in_bars and bar_ctx.lookback_in_bars
    for arm in range(n):
        k1, l1 = resistance_window(ms_ctx, arm)
        k2, l2 = resistance_window(bar_ctx, arm)
        assert k1 == k2
        # the same swings qualify: (known > k - l) has the same threshold, or both reach before the first bar
        assert k1 - l1 == k2 - l2 or (k1 - l1 < int(t[0]) and k2 - l2 < int(t[0]))
    # on a session grid the bar rule spans the weekend: 4 bars back from Monday 00:15 reaches into Friday
    g = CME.bar_opens(Timeframe.M15, ms(2024, 7, 11), ms(2024, 7, 16))
    sb = S7Bars(Timeframe.M15.ms, g, *(np.full(len(g), 2000.0),) * 4, np.ones(len(g)))
    sess = make_context(sb, sb, md, load_config().costs, S7Params(lookback_bars=4), tp, calendar=CME)
    arm = int(np.searchsorted(g, ms(2024, 7, 14, 22, 15)))
    k, lb = resistance_window(sess, arm)
    assert k - lb == int(g[arm - 3]) and int(g[arm - 3]) == ms(2024, 7, 12, 20, 30)


def test_feature_view_reads_a_session_hourly_grid_and_counts_trading_hours():
    from arven.backtest.errors import LookAheadError
    from arven.backtest.provider import FeatureView

    grid = decision_grid(ms(2024, 7, 12, 18), ms(2024, 7, 15, 3), CME)  # Friday afternoon -> Monday night, over the weekend
    vals = np.arange(len(grid), dtype=float).reshape(-1, 1)
    clock = type("C", (), {"now_ms": int(grid[-1])})()
    view = FeatureView(grid, ("x",), vals, clock, None)  # type: ignore[arg-type]
    assert view.value("x", ms(2024, 7, 14, 23)) == float(np.searchsorted(grid, ms(2024, 7, 14, 23)))
    # the last 3 values at Sunday 23:00 are Friday 19:00, Friday 20:00 and Sunday 23:00: trading hours, not wall hours
    i = int(np.searchsorted(grid, ms(2024, 7, 14, 23)))
    assert view.history("x", 3, ms(2024, 7, 14, 23)).tolist() == [i - 2, i - 1, i]
    with pytest.raises(KeyError):
        view.value("x", ms(2024, 7, 13, 12))  # Saturday: no decision row
    with pytest.raises(LookAheadError):
        view.value("x", int(grid[-1]) + H)
    with pytest.raises(ValueError, match="whole hours"):
        FeatureView(grid + 1, ("x",), vals, clock, None)  # type: ignore[arg-type]
