"""Phase 5: the always-on runtime loop (``arven.paper.runtime``) - offline, no real network/sleep.

Reuses the exact synthetic-environment helpers ``test_paper_runs.py`` already built for Stage 8 (same
directory, same import pattern already used elsewhere in this project, e.g. ``tests/news/test_runs.py``
importing from ``test_rss.py``), rather than duplicating them.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest
from bt_helpers import HOUR
from test_paper_runs import T0, fake_downloader, synthetic_splits_overrides

from arven.backtest.baselines import NoTrade
from arven.core.backtest_config import load_backtest_config
from arven.core.features_config import load_features_config
from arven.core.time import from_ms
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.storage.db import connect
from arven.paper.runtime import is_stale, log_event, read_heartbeat, run_forever, run_once, write_heartbeat

MIN = 60_000


@pytest.fixture
def env(make_config):
    """A minimal environment: 4 days of flat synthetic 1m history (enough that the forward window is
    reachable), no real decisions needed - these tests check the *loop's own* orchestration, not decision
    correctness (already covered by test_paper_runs.py / test_event_backtest_equivalence.py)."""
    app = make_config(**synthetic_splits_overrides())
    fcfg, bt = load_features_config(), load_backtest_config()
    con = connect(app.data.database_path)
    n_minutes = 4 * 24 * 60
    rows = [
        ("BTCUSDT", T0 + k * MIN, T0 + k * MIN + MIN, 100.0, 100.0, 100.0, 100.0, 1.0, 1.0, 1, 0.5, 0.5, "seed", 0)
        for k in range(n_minutes)
    ]
    from bt_helpers import bulk_insert_1m

    bulk_insert_1m(con, rows)
    resample(con, "BTCUSDT", from_ms(T0), from_ms(T0 + n_minutes * MIN), DERIVED_TIMEFRAMES)
    con.close()
    return app, fcfg, bt


def no_trade_factory():
    return NoTrade()


# --- run_once --------------------------------------------------------------------------------------


def test_run_once_ticks_on_the_first_call_even_with_nothing_new(env):
    app, fcfg, bt = env
    now = from_ms(T0 + 4 * 24 * HOUR)
    result = run_once(app, fcfg, bt, no_trade_factory, now=now, downloader=fake_downloader(app), last_end_ms=None)
    assert result.status == "ticked" and result.outcome is not None and result.end_ms is not None


def test_run_once_is_idle_when_the_decision_grid_has_not_advanced(env):
    app, fcfg, bt = env
    now = from_ms(T0 + 4 * 24 * HOUR)
    first = run_once(app, fcfg, bt, no_trade_factory, now=now, downloader=fake_downloader(app), last_end_ms=None)
    second = run_once(app, fcfg, bt, no_trade_factory, now=now, downloader=fake_downloader(app), last_end_ms=first.end_ms)
    assert second.status == "idle" and second.outcome is None
    assert second.end_ms == first.end_ms


def test_run_once_ticks_again_once_an_hour_has_passed(env):
    app, fcfg, bt = env
    first = run_once(app, fcfg, bt, no_trade_factory, now=from_ms(T0 + 4 * 24 * HOUR), downloader=fake_downloader(app), last_end_ms=None)
    later = run_once(
        app, fcfg, bt, no_trade_factory, now=from_ms(T0 + 4 * 24 * HOUR + HOUR), downloader=fake_downloader(app), last_end_ms=first.end_ms,
    )
    assert later.status == "ticked"
    assert later.end_ms > first.end_ms


class _FailingOpener:
    """Raises on every call - simulates a REST endpoint that is completely unreachable."""

    def __call__(self, request, timeout):
        raise OSError("simulated network failure")


def test_run_once_never_raises_on_a_rest_error_and_reports_it(env):
    app, fcfg, bt = env
    from arven.data.download import Downloader, RetryPolicy

    bad_downloader = Downloader(RetryPolicy.from_config(app.download), opener=_FailingOpener(), sleep=lambda s: None)
    now = from_ms(T0 + 4 * 24 * HOUR)
    result = run_once(app, fcfg, bt, no_trade_factory, now=now, downloader=bad_downloader, last_end_ms=None)
    assert result.status == "error"
    assert result.detail  # non-empty: something informative was recorded, not swallowed silently


def test_run_once_before_forward_start_is_idle_not_an_error(env):
    app, fcfg, bt = env
    result = run_once(app, fcfg, bt, no_trade_factory, now=from_ms(T0 + 1 * HOUR), downloader=fake_downloader(app), last_end_ms=None)
    # before forward_start, run_paper_tick returns window=None; run_once must not crash on that.
    assert result.status in ("ticked", "idle")


# --- heartbeat / log --------------------------------------------------------------------------------


def test_heartbeat_round_trips(tmp_path):
    path = tmp_path / "heartbeat.json"
    assert read_heartbeat(path) is None
    write_heartbeat(path, status="ticked", checked_at_ms=1000, last_tick_ms=1000, detail="")
    hb = read_heartbeat(path)
    assert hb == {"status": "ticked", "checked_at_ms": 1000, "last_tick_ms": 1000, "detail": ""}


def test_heartbeat_write_is_atomic_no_tmp_file_left_behind(tmp_path):
    path = tmp_path / "sub" / "heartbeat.json"
    write_heartbeat(path, status="idle", checked_at_ms=1000, last_tick_ms=None)
    leftovers = list(path.parent.glob(".heartbeat-*"))
    assert leftovers == []


def test_is_stale_true_with_no_heartbeat_at_all():
    assert is_stale(None, now_ms=1_000_000, max_age_ms=60_000)


def test_is_stale_false_when_recently_checked():
    hb = {"status": "idle", "checked_at_ms": 1_000_000, "last_tick_ms": None, "detail": ""}
    assert not is_stale(hb, now_ms=1_000_000 + 30_000, max_age_ms=60_000)


def test_is_stale_true_when_too_old():
    hb = {"status": "idle", "checked_at_ms": 1_000_000, "last_tick_ms": None, "detail": ""}
    assert is_stale(hb, now_ms=1_000_000 + 90_000, max_age_ms=60_000)


def test_log_event_appends_json_lines(tmp_path):
    path = tmp_path / "runtime.jsonl"
    log_event(path, event="tick", status="idle")
    log_event(path, event="tick", status="ticked")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
    assert [line["status"] for line in lines] == ["idle", "ticked"]
    assert all("time_ms" in line for line in lines)


# --- run_forever -------------------------------------------------------------------------------------


def test_run_forever_stops_after_max_iterations_and_writes_a_heartbeat_each_time(env, tmp_path):
    app, fcfg, bt = env
    heartbeat, log = tmp_path / "heartbeat.json", tmp_path / "runtime.jsonl"
    times = iter([from_ms(T0 + 4 * 24 * HOUR), from_ms(T0 + 4 * 24 * HOUR), from_ms(T0 + 4 * 24 * HOUR + HOUR)])

    asyncio.run(
        run_forever(
            app, fcfg, bt, no_trade_factory, heartbeat_path=heartbeat, log_path=log, poll_seconds=0,
            downloader_factory=lambda: fake_downloader(app), now_fn=lambda: next(times), max_iterations=3,
        )
    )
    hb = read_heartbeat(heartbeat)
    assert hb is not None
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    statuses = [json.loads(line)["status"] for line in lines]
    assert statuses == ["ticked", "idle", "ticked"]  # tick, then idle (same hour), then tick (next hour)


def test_run_forever_stops_immediately_when_the_stop_event_is_already_set(env, tmp_path):
    app, fcfg, bt = env
    stop_event = asyncio.Event()
    stop_event.set()
    heartbeat, log = tmp_path / "heartbeat.json", tmp_path / "runtime.jsonl"

    asyncio.run(
        run_forever(
            app, fcfg, bt, no_trade_factory, heartbeat_path=heartbeat, log_path=log,
            downloader_factory=lambda: fake_downloader(app), stop_event=stop_event,
        )
    )
    assert read_heartbeat(heartbeat) is None  # the loop body never ran at all


def test_run_forever_can_be_stopped_mid_run_by_an_external_event(env, tmp_path):
    app, fcfg, bt = env
    stop_event = asyncio.Event()
    heartbeat, log = tmp_path / "heartbeat.json", tmp_path / "runtime.jsonl"

    async def stop_after_first_tick():
        await run_forever(
            app, fcfg, bt, no_trade_factory, heartbeat_path=heartbeat, log_path=log, poll_seconds=0.05,
            downloader_factory=lambda: fake_downloader(app), now_fn=lambda: from_ms(T0 + 4 * 24 * HOUR),
            stop_event=stop_event, max_iterations=None,
        )

    async def main():
        task = asyncio.create_task(stop_after_first_tick())
        await asyncio.sleep(0.2)  # let a few idle iterations happen
        stop_event.set()
        await task

    asyncio.run(main())
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    assert json.loads(lines[0])["status"] == "ticked"
