"""Stage 8 end-to-end: synthetic DB -> REST tail (fake, offline) -> resample -> forward window -> the real
Stage5Pipeline through the real Backtester -> a written run artifact under data/paper/.

Uses a compact, fully synthetic splits.yaml (overridden via ``make_config``) so the forward period is
reachable without waiting for the real 2026-07-01 ``forward_start`` - everything else (data.history_start,
the real Stage 3/4/5 code) is exercised exactly as in production, just on a tiny time range.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from arven.backtest.baselines import NoTrade
from arven.core.backtest_config import load_backtest_config
from arven.core.features_config import load_features_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.splitguard import BacktestPeriod, SealedAccessError
from arven.core.strategies_config import load_strategies_config
from arven.core.time import from_ms
from arven.data.download import Downloader, RetryPolicy
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.storage.db import connect
from arven.decision.pipeline import Stage5Pipeline
from arven.paper.runs import (
    latest_forward_window_end_ms,
    load_paper_inputs,
    paper_dir,
    run_paper_tick,
    update_market_data,
)
from arven.runs import make_guard, sealed_log_path
from bt_helpers import bulk_insert_1m, bulk_insert_funding
from rest_helpers import FakeBinanceRestOpener

HOUR = 3_600_000
DAY = 24 * HOUR
MIN = 60_000
T0 = 1_609_718_400_000  # 2021-01-04 00:00 UTC (matches bt_helpers.T0 / synthetic_market.START_MS)


def synthetic_splits_overrides() -> dict[str, str]:
    """A compact, self-consistent timeline anchored at T0 so the forward period is reachable in a fast test."""
    def day(n: int) -> str:
        return from_ms(T0 + n * DAY).date().isoformat()

    return {
        "default__data__history_start": day(0),
        "splits__development__start": day(0),
        "splits__development__end": day(1),
        "splits__validation__start": day(1),
        "splits__validation__end": day(2),
        "splits__test__start": day(2),
        "splits__test__end": day(3),
        "splits__forward_start": day(3),
    }


def fake_downloader(app, kline_opens=(), funding_times=()) -> Downloader:
    opener = FakeBinanceRestOpener(list(kline_opens), list(funding_times))
    return Downloader(RetryPolicy.from_config(app.download), opener=opener, sleep=lambda s: None)


@pytest.fixture
def env(make_config):
    app = make_config(**synthetic_splits_overrides())
    fcfg, bt = load_features_config(), load_backtest_config()
    con = connect(app.data.database_path)
    rng = np.random.default_rng(7)
    n_minutes = 10 * 24 * 60  # 10 days of 1m bars: 3 days of history + forward_start + headroom
    px = 100.0
    rows = []
    for k in range(n_minutes):
        t = T0 + k * MIN
        o = float(px)
        px *= 1 + rng.normal(0.0, 3e-4)
        rows.append(("BTCUSDT", t, t + MIN, o, max(o, float(px)), min(o, float(px)), float(px), 1.0, 1.0, 1, 0.5, 0.5, "seed", 0))
    bulk_insert_1m(con, rows)
    fund_rows = [("BTCUSDT", T0 + k * 8 * HOUR, T0 + k * 8 * HOUR, 0.0001, 8, T0 + k * 8 * HOUR, "seed", 0) for k in range(30)]
    bulk_insert_funding(con, fund_rows)
    resample(con, "BTCUSDT", from_ms(T0), from_ms(T0 + n_minutes * MIN), DERIVED_TIMEFRAMES)
    con.close()
    return app, fcfg, bt


def make_pipeline(bt):
    return Stage5Pipeline(load_regime_config(), load_strategies_config(), load_risk_config(), bt)


# --- latest_forward_window_end_ms -----------------------------------------------------------------


def test_latest_forward_window_end_ms_is_the_last_closed_hours_close_plus_one_hour(env):
    app, *_ = env
    now = from_ms(T0 + 3 * DAY + 2 * HOUR + 17 * MIN)  # mid-way through the T0+3d+2h..3h bar
    end = latest_forward_window_end_ms(app, now)
    # last closed+available bar is [T0+3d+1h, T0+3d+2h); its close (T0+3d+2h) is the last decision time;
    # end_ms is exclusive, one more hour out.
    assert end == T0 + 3 * DAY + 3 * HOUR


def test_latest_forward_window_end_ms_respects_the_bar_availability_delay(make_config):
    app = make_config(default__data__bar_availability_delay_seconds=120, **synthetic_splits_overrides())
    now = from_ms(T0 + 3 * DAY + HOUR + MIN)  # 1 minute after the T0+3d..+1h bar closed; delay needs 2
    end = latest_forward_window_end_ms(app, now)
    # the bar closing at T0+3d+1h is not yet "available" under the 2-minute delay, so the latest usable
    # decision time is still T0+3d (one hour earlier than the no-delay case would give).
    assert end == T0 + 3 * DAY + HOUR


# --- update_market_data (REST tail via the fake, offline opener) ----------------------------------


def test_update_market_data_is_a_safe_no_op_when_nothing_new_is_available(env):
    app, *_ = env
    con = connect(app.data.database_path)
    before = con.execute("SELECT count(*) FROM ohlcv_1m").fetchone()[0]
    now = from_ms(T0 + 4 * DAY)
    summary = update_market_data(app, con, T0 + 4 * DAY, fake_downloader(app), now)
    assert summary.ok and summary.klines_written == 0
    assert con.execute("SELECT count(*) FROM ohlcv_1m").fetchone()[0] == before
    con.close()


def test_update_market_data_resamples_the_whole_new_range_not_just_a_fixed_lookback(make_config):
    """Regression test for a real bug found via a live run: a large REST catch-up (here, 9 days of new 1m
    bars - far more than the 2-day resample buffer) must get its derived 1h bars built for its *entire*
    range, not just the last couple of days. The original implementation resampled a fixed lookback window
    and silently left most of a large catch-up's derived bars unbuilt, starving every feature after it of
    data and producing zero decisions for the whole period."""
    app = make_config(**synthetic_splits_overrides())
    con = connect(app.data.database_path)
    # seed only the first day directly (as if a prior tick had already caught up to here)
    rows = [("BTCUSDT", T0 + k * MIN, T0 + k * MIN + MIN, 100.0, 101.0, 99.0, 100.5, 1.0, 100.0, 10, 0.5, 50.0, "seed", 0)
            for k in range(24 * 60)]
    bulk_insert_1m(con, rows)
    resample(con, "BTCUSDT", from_ms(T0), from_ms(T0 + DAY), DERIVED_TIMEFRAMES)
    con.close()

    # a REST catch-up of 9 more days - much larger than RESAMPLE_BOUNDARY_BUFFER_MS (2 days)
    new_opens = list(range(T0 + DAY, T0 + 10 * DAY, MIN))
    con = connect(app.data.database_path)
    summary = update_market_data(app, con, T0 + 10 * DAY, fake_downloader(app, kline_opens=new_opens), from_ms(T0 + 10 * DAY))
    assert summary.ok and summary.klines_written == len(new_opens)
    incomplete = con.execute(
        "SELECT count(*) FROM ohlcv WHERE symbol='BTCUSDT' AND timeframe='1h' AND open_time_ms >= ? AND open_time_ms < ? AND NOT is_complete",
        [T0 + DAY, T0 + 10 * DAY],
    ).fetchone()[0]
    total_hours = con.execute(
        "SELECT count(*) FROM ohlcv WHERE symbol='BTCUSDT' AND timeframe='1h' AND open_time_ms >= ? AND open_time_ms < ?",
        [T0 + DAY, T0 + 10 * DAY],
    ).fetchone()[0]
    assert total_hours == 9 * 24  # every hour of the new 9-day range got a derived 1h bar, not just the last 2 days
    assert incomplete == 0
    con.close()


# --- load_paper_inputs ------------------------------------------------------------------------------


def test_load_paper_inputs_reads_exactly_the_forward_window(env):
    app, fcfg, bt = env
    guard = make_guard(app)
    end_ms = T0 + 3 * DAY + 24 * HOUR  # one day into the forward period
    window = guard.resolve(BacktestPeriod.FORWARD, end_ms=end_ms)
    inputs = load_paper_inputs(app, fcfg, window)
    assert inputs.market.window_start_ms == window.start_ms and inputs.market.window_end_ms == window.end_ms
    assert len(inputs.features.t_ms) == window.n_hours
    assert int(inputs.features.t_ms[0]) == window.start_ms and int(inputs.features.t_ms[-1]) == window.end_ms - HOUR
    assert {r["dataset"] for r in inputs.data_ranges} == {"ohlcv_1m", "funding_rates", "features"}
    # feat_ready is always 0 here: 10 days of synthetic history can never satisfy the real warm-up
    # requirements (e.g. h4_ema_dist_200 needs 1000 4h bars) - expected, not a bug in this test.
    i = inputs.features.names.index("feat_ready")
    assert np.all(inputs.features.values[:, i] == 0.0)


# --- run_paper_tick end-to-end -----------------------------------------------------------------------


def test_run_paper_tick_before_forward_start_does_nothing(env):
    app, fcfg, bt = env
    outcome = run_paper_tick(app, fcfg, bt, NoTrade(), now=from_ms(T0 + 1 * DAY), downloader=fake_downloader(app))
    assert outcome.window is None and outcome.run is None


def test_run_paper_tick_runs_the_real_pipeline_and_writes_an_artifact(env):
    app, fcfg, bt = env
    pipeline = make_pipeline(bt)
    now = from_ms(T0 + 4 * DAY)
    outcome = run_paper_tick(app, fcfg, bt, pipeline, now=now, downloader=fake_downloader(app))
    assert outcome.window is not None and outcome.window.period.value == "forward"
    assert not outcome.window.sealed
    out = outcome.run
    assert out is not None
    assert out.run_dir is not None and out.run_dir.exists()
    manifest = json.loads((out.run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["period"] == "forward" and manifest["touched_test_set"] is False
    # feat_ready never reaches 1 in this short synthetic history -> every decision is vetoed, 0 trades.
    assert out.metrics["n_trades"] == 0
    assert out.metrics["final_equity"] == pytest.approx(bt.initial_equity_usdt)
    index = [json.loads(x) for x in (paper_dir(app) / "runs.jsonl").read_text().splitlines()]
    assert index[-1]["run_id"] == out.run_id


def test_run_paper_tick_writes_decisions_jsonl_from_the_providers_own_history(env):
    app, fcfg, bt = env
    pipeline = make_pipeline(bt)
    now = from_ms(T0 + 4 * DAY)
    outcome = run_paper_tick(app, fcfg, bt, pipeline, now=now, downloader=fake_downloader(app))
    decisions_path = outcome.run.run_dir / "decisions.jsonl"
    assert decisions_path.exists()
    lines = [json.loads(line) for line in decisions_path.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == len(pipeline.history)
    assert lines[0]["t_ms"] == pipeline.history[0].t_ms
    assert lines[0]["proposed_action"] == "NO_TRADE"  # feat_ready never reaches 1 in this short history


def test_run_paper_tick_writes_no_decisions_jsonl_for_a_provider_without_history(env):
    app, fcfg, bt = env
    outcome = run_paper_tick(app, fcfg, bt, NoTrade(), now=from_ms(T0 + 4 * DAY), downloader=fake_downloader(app))
    assert not (outcome.run.run_dir / "decisions.jsonl").exists()


def test_run_paper_tick_is_catch_up_capable_a_later_tick_extends_the_window(env):
    app, fcfg, bt = env
    first = run_paper_tick(app, fcfg, bt, NoTrade(), now=from_ms(T0 + 4 * DAY), downloader=fake_downloader(app))
    second = run_paper_tick(app, fcfg, bt, NoTrade(), now=from_ms(T0 + 5 * DAY), downloader=fake_downloader(app))
    assert first.window.start_ms == second.window.start_ms == T0 + 3 * DAY  # always forward_start
    assert second.window.end_ms > first.window.end_ms  # the window grows with "now"


def test_run_paper_tick_never_resolves_or_touches_the_sealed_test_period(env):
    app, fcfg, bt = env
    with pytest.raises(SealedAccessError):
        make_guard(app).resolve(BacktestPeriod.TEST)
    assert not sealed_log_path(app).exists()
    run_paper_tick(app, fcfg, bt, NoTrade(), now=from_ms(T0 + 4 * DAY), downloader=fake_downloader(app))
    assert not sealed_log_path(app).exists()  # a paper tick never writes to the sealed-access log
