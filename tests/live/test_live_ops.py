"""Daily housekeeping, the forward review rule and the weekly report (arven.live.maintenance / review / loop)."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime

import pytest

from arven.core.live_config import LiveConfig
from arven.live.loop import LoopState, poll_once
from arven.live.maintenance import plan_prune, prune_paper_runs
from arven.live.review import forward_review, max_drawdown_r
from arven.telegram.messages import WeeklyReportRow, format_weekly_report
from tests.live.test_live_loop import Recorder

# --- the forward review rule (hand-computed) -----------------------------------------------------------------------


def test_review_hand_computed_interval():
    rs = [1.0, -1.0, 2.0, -1.0]  # mean 0.25; squared deviations .5625+1.5625+3.0625+1.5625 = 6.75; sample sd 1.5
    out = forward_review(rs, min_closed=2)
    half = 1.959963984540054 * 1.5 / math.sqrt(4)
    assert out["mean_r"] == pytest.approx(0.25)
    assert out["ci_low"] == pytest.approx(0.25 - half) and out["ci_high"] == pytest.approx(0.25 + half)
    assert out["profit_factor"] == pytest.approx(3.0 / 2.0)
    assert out["max_dd_r"] == pytest.approx(1.0)
    assert out["verdict"] == "inconclusive"


def test_review_verdicts():
    assert forward_review([-1.0] * 10 + [0.5] * 2, min_closed=30)["verdict"] == "too_few"
    assert forward_review([], min_closed=30)["verdict"] == "too_few"
    assert forward_review([-1.0, -0.9, -1.1] * 10, min_closed=30)["verdict"] == "losing"
    assert forward_review([1.0, 0.9, 1.1] * 10, min_closed=30)["verdict"] == "positive"
    assert forward_review([1.0, -1.0] * 15, min_closed=30)["verdict"] == "inconclusive"


def test_max_drawdown_follows_the_order():
    assert max_drawdown_r([1, -2, 3, -1, -1]) == 2
    assert max_drawdown_r([-1, -1]) == 2
    assert max_drawdown_r([]) == 0


# --- paper-run retention -------------------------------------------------------------------------------------------


def test_prune_keeps_recent_and_last_of_each_day():
    names = ["20261014T100000Z-aa", "20261014T230000Z-aa", "20261015T010000Z-aa", "20261015T120000Z-aa",
             "20261016T000000Z-aa", "20261016T010000Z-aa", "runs.jsonl", "notarun"]
    kept, removed = plan_prune(names, keep_recent=2)
    assert removed == ["20261014T100000Z-aa", "20261015T010000Z-aa"]
    assert kept == ["20261014T230000Z-aa", "20261015T120000Z-aa", "20261016T000000Z-aa", "20261016T010000Z-aa"]
    with pytest.raises(ValueError):
        plan_prune(names, keep_recent=0)


def test_prune_touches_only_run_directories(tmp_path):
    for n in ["20261014T100000Z-aa", "20261014T230000Z-aa", "20261015T120000Z-aa"]:
        (tmp_path / n).mkdir()
        (tmp_path / n / "decisions.jsonl").write_bytes(b"x" * 10)
    (tmp_path / "runs.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "keepme").mkdir()
    dry = prune_paper_runs(tmp_path, keep_recent=1, apply=False)
    assert dry.removed == ("20261014T100000Z-aa",) and dry.bytes_freed == 10
    assert (tmp_path / "20261014T100000Z-aa").exists()
    res = prune_paper_runs(tmp_path, keep_recent=1)
    assert res.removed == ("20261014T100000Z-aa",)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["20261014T230000Z-aa", "20261015T120000Z-aa", "keepme", "runs.jsonl"]
    assert prune_paper_runs(tmp_path / "missing").removed == ()


# --- the loop: once a day / once a week ----------------------------------------------------------------------------


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_maintenance_runs_once_a_day_after_its_hour(tmp_path):
    rec, live, state = Recorder(), LiveConfig(), LoopState()
    calls = []
    deps = rec.deps(maintenance=lambda now: calls.append(now) or {"backup": "x.zip"})
    log = tmp_path / "l.jsonl"
    asyncio.run(poll_once(live, deps, state, datetime(2026, 10, 16, 0, 30, tzinfo=UTC), log))
    assert calls == []  # before maintenance.hour_utc (01)
    asyncio.run(poll_once(live, deps, state, datetime(2026, 10, 16, 1, 0, 10, tzinfo=UTC), log))
    asyncio.run(poll_once(live, deps, state, datetime(2026, 10, 16, 1, 0, 30, tzinfo=UTC), log))
    assert len(calls) == 1 and state.maintenance_date == "2026-10-16"
    asyncio.run(poll_once(live, deps, state, datetime(2026, 10, 17, 1, 5, tzinfo=UTC), log))
    assert len(calls) == 2
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [e["status"] for e in events if e["event"] == "maintenance"] == ["ok", "ok"]


def test_failed_maintenance_is_not_retried_every_poll_and_alerts(tmp_path):
    rec, live, state = Recorder(), LiveConfig(), LoopState()
    calls = []

    def broken(now):
        calls.append(now)
        raise OSError("disk full")

    deps = rec.deps(maintenance=broken)
    for sec in (10, 30, 50):
        asyncio.run(poll_once(live, deps, state, datetime(2026, 10, 16, 2, 0, sec, tzinfo=UTC), tmp_path / "l"))
    assert len(calls) == 1
    assert ("maintenance:2026-10-16", "daily backup failed") in rec.system


def test_weekly_report_on_the_configured_weekday_once(tmp_path):
    rec, live, state = Recorder(), LiveConfig(), LoopState()
    weeks = []
    deps = rec.deps(queue_weekly_report=lambda today: weeks.append(today))
    sunday, monday = datetime(2026, 10, 18, 12, tzinfo=UTC), datetime(2026, 10, 19, 0, 0, 10, tzinfo=UTC)
    assert sunday.weekday() == 6 and monday.weekday() == 0
    asyncio.run(poll_once(live, deps, state, sunday, tmp_path / "l"))
    asyncio.run(poll_once(live, deps, state, monday, tmp_path / "l"))
    asyncio.run(poll_once(live, deps, state, monday.replace(second=40), tmp_path / "l"))
    assert weeks == ["2026-10-19"] and state.weekly_date == "2026-10-19"


def test_old_state_files_without_the_new_fields_still_load(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"done_through_ms": 1, "summary_date": "2026-10-15", "telegram_update_id": 3}), encoding="utf-8")
    st = LoopState.load(path)
    assert st.done_through_ms == 1 and st.weekly_date is None and st.maintenance_date is None


def test_weekly_report_text():
    rows = (
        WeeklyReportRow("s6", "EXPERIMENTAL", 166, 3, -23.49, 0.41, -0.141, -0.30, -0.02, 30.2, "losing", 5, -1.5),
        WeeklyReportRow("cs", "EXPERIMENTAL", 3, 0, 1.16, 1.0, 0.387, None, None, 0.0, "too_few", 0, 0.0),
    )
    text = format_weekly_report("2026-10-12 - 2026-10-18", "2026-07-01", rows)
    assert "s6 [EXPERIMENTAL]" in text and "166 closed (3 open), -23.49R" in text
    assert "95% CI [-0.30, -0.02]" in text and "LOSING" in text
    assert "cs [EXPERIMENTAL]" in text and "95% CI n/a" in text and "too few" in text
    assert "No strategy has a proven edge" in text and "not a real order" in text
