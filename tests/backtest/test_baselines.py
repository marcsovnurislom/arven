"""No-trade, buy-and-hold and seeded random entry."""

import numpy as np
import pytest
from bt_helpers import HOUR, T0, Scripted, app_config, bt_config, features_for, make_market, window, zero_cost_app

from arven.backtest.baselines import BuyAndHold, NoTrade, RandomEntry
from arven.backtest.engine import Backtester
from arven.backtest.provider import FeatureData, PrepareInfo
from arven.core.types import Action


def prep(hours, ready_from_hour=0, first_ready=True):
    grid = T0 + np.arange(hours, dtype=np.int64) * HOUR
    return PrepareInfo(grid, T0 + hours * HOUR, int(grid[ready_from_hour]) if first_ready else None)


def features_ready_from(win, ready_hour):
    n = win.n_hours
    t = win.start_ms + np.arange(n, dtype=np.int64) * HOUR
    flag = (np.arange(n) >= ready_hour).astype(float).reshape(-1, 1)
    return FeatureData(t, ("feat_ready",), flag, int(t[ready_hour]) if ready_hour < n else None)


def test_no_trade_is_exactly_flat():
    market = make_market(24)
    win = window(24)
    res = Backtester(app_config(), bt_config(), win, market, features_for(win)).run(NoTrade())
    assert not res.trades and not res.fills and res.final_wallet == 10_000.0
    assert {p.equity for p in res.equity} == {10_000.0}


def test_buy_and_hold_enters_once_at_the_first_ready_decision_and_holds_to_the_end():
    hours = 12
    market = make_market(hours)
    win = window(hours)
    res = Backtester(zero_cost_app(), bt_config(), win, market, features_ready_from(win, 4)).run(BuyAndHold(1.0))
    (t,) = res.trades
    assert t.entry_time_ms == T0 + 4 * HOUR and t.exit_reason.value == "END_OF_PERIOD" and t.exit_time_ms == T0 + hours * HOUR
    assert res.signal_counts["entry"] == 1


def test_buy_and_hold_never_enters_when_features_are_never_ready_and_does_not_retry_after_a_rejection():
    market = make_market(6)
    win = window(6)
    res = Backtester(zero_cost_app(), bt_config(), win, market, features_ready_from(win, 99)).run(BuyAndHold(1.0))
    assert not res.trades and res.signal_counts["entry"] == 0
    # 4.0 x equity exceeds the leverage cap: rejected once, and never retried
    res = Backtester(zero_cost_app(), bt_config(), win, market, features_for(win)).run(BuyAndHold(4.0))
    assert not res.trades and res.signal_counts["entry"] == 1


def new_random(i, **kw):
    params = dict(base_seed=42, spawn_index=i, n_trades=20, holding_minutes=120, notional_fraction=0.5)
    params.update(kw)
    return RandomEntry(**params)


def test_random_entry_schedule_rules():
    hours = 24 * 30
    info = prep(hours, ready_from_hour=100)
    r = new_random(0, n_trades=25)
    r.prepare(info)
    sched = r.schedule
    times = sorted(sched)
    assert len(times) == r.placed == 25
    assert all(t >= T0 + 100 * HOUR for t in times)  # only after the warm-up
    assert all(t + 120 * 60_000 + HOUR < T0 + hours * HOUR for t in times)  # the time stop lies inside the window
    span = 120 * 60_000 + HOUR
    assert all(b - a >= span for a, b in zip(times, times[1:]))  # never overlapping
    assert set(sched.values()) <= {Action.LONG, Action.SHORT} and len(set(sched.values())) == 2


def test_random_entry_is_reproducible_and_seeds_differ():
    info = prep(24 * 30)
    a, b, c = new_random(3), new_random(3), new_random(4)
    for r in (a, b, c):
        r.prepare(info)
    assert a.schedule == b.schedule and a.schedule != c.schedule


def test_random_entry_seed_derivation_equals_seedsequence_spawn():
    info = prep(24 * 30)
    r = new_random(7)
    r.prepare(info)
    # identical to the documented derivation: children of SeedSequence(42)
    child = np.random.SeedSequence(42).spawn(10)[7]
    rng = np.random.Generator(np.random.PCG64(child))
    eligible = info.grid_ms[(info.grid_ms + 120 * 60_000 + HOUR < info.window_end_ms)]
    first_pick = int(eligible[int(rng.permutation(len(eligible))[0])])
    assert first_pick in r.schedule


def test_random_entry_schedule_does_not_depend_on_prices():
    hours = 24 * 10
    win = window(hours)
    feats = features_for(win)
    calm = make_market(hours)
    wild = make_market(hours, {i: (30_000.0 + (i % 7) * 50, 31_000.0, 29_000.0, 30_000.0) for i in range(0, hours * 60, 3)})
    r1, r2 = new_random(1, n_trades=10), new_random(1, n_trades=10)
    a = Backtester(zero_cost_app(), bt_config(), win, calm, feats).run(r1)
    b = Backtester(zero_cost_app(), bt_config(), win, wild, feats).run(r2)
    assert r1.schedule == r2.schedule
    assert [t.signal_ms for t in a.trades] == [t.signal_ms for t in b.trades] == sorted(r1.schedule)


def test_random_entry_reports_a_shortfall_when_the_window_is_too_small_and_exits_by_time_stop():
    hours = 24
    r = new_random(0, n_trades=50, holding_minutes=600)
    r.prepare(prep(hours))
    assert r.placed < 50 and r.placed >= 1
    market = make_market(hours)
    win = window(hours)
    res = Backtester(zero_cost_app(), bt_config(), win, market, features_for(win)).run(r)
    assert res.trades and all(t.exit_reason.value == "TIME_STOP" for t in res.trades)
    assert all(t.minutes_held == pytest.approx(600.0) for t in res.trades)


def test_random_entry_skips_a_scheduled_trade_when_features_are_not_ready_and_counts_it():
    hours = 24 * 5
    win = window(hours)
    market = make_market(hours)
    r = new_random(2, n_trades=5, holding_minutes=60)
    res = Backtester(zero_cost_app(), bt_config(), win, market, features_ready_from(win, 0)).run(r)
    assert len(res.trades) == 5 and r.skipped_not_ready == 0
    # never ready (no first-ready date in the manifest): the schedule is planned from time-only information,
    # and the runtime readiness gate blocks every scheduled entry
    r2 = new_random(2, n_trades=5, holding_minutes=60)
    res2 = Backtester(zero_cost_app(), bt_config(), win, market, features_ready_from(win, 999)).run(r2)
    assert r2.placed == 5 and r2.skipped_not_ready == 5 and not res2.trades


def test_random_entry_describe_records_the_seed_information():
    d = new_random(5).describe()
    assert d["name"] == "random_entry" and d["base_seed"] == 42 and d["spawn_index"] == 5
    assert d["algorithm"] == "PCG64/SeedSequence" and d["numpy_version"] == np.__version__
    with pytest.raises(ValueError):
        RandomEntry(base_seed=1, spawn_index=0, n_trades=1, holding_minutes=60, notional_fraction=1.0, direction_mode="momentum")
