"""The always-on loop's orchestration (``arven.live.loop``) with fake dependencies - no network, no real sleep."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from arven.core.live_config import LiveConfig
from arven.core.time import from_ms
from arven.live.loop import LoopDeps, LoopState, due_close_ms, poll_once, run_live_forever
from arven.paper.runtime import read_heartbeat

MIN = 60_000
H = 3_600_000
T = 1_790_000_000_000 // H * H  # a whole hour


@dataclass
class FakeOut:
    status: str
    through_ms: int | None
    detail: str = ""
    strategies: dict = field(default_factory=dict)
    queued_alerts: int = 0


class Recorder:
    def __init__(self, statuses=None, through_lag=0):
        self.ticks, self.legacy, self.system, self.daily, self.sent = [], [], [], [], 0
        self.statuses = list(statuses or [])
        self.through_lag = through_lag

    def deps(self, **over) -> LoopDeps:
        def tick(now):
            self.ticks.append(now)
            st = self.statuses.pop(0) if self.statuses else "ok"
            if st == "raise":
                raise RuntimeError("tick failed")
            due = due_close_ms(int(now.timestamp() * 1000), 5_000)
            return FakeOut(st, None if st == "stale" else due - self.through_lag)

        def send():
            self.sent += 1

        d = LoopDeps(live_tick=tick, legacy_tick=lambda now: self.legacy.append(now) or type("R", (), {"status": "ticked", "detail": ""})(),
                     send_telegram=send, poll_commands=lambda last: last + 1,
                     queue_system=lambda key, title, detail: self.system.append((key, title)), queue_daily_summary=lambda day: self.daily.append(day))
        for k, v in over.items():
            setattr(d, k, v)
        return d


def run(coro):
    return asyncio.run(coro)


def test_ticks_only_when_a_new_close_is_due(tmp_path):
    rec, live, state = Recorder(), LiveConfig(), LoopState()
    log = tmp_path / "log.jsonl"
    run(poll_once(live, rec.deps(), state, from_ms(T + 15 * MIN + 10_000), log))
    run(poll_once(live, rec.deps(), state, from_ms(T + 15 * MIN + 30_000), log))
    run(poll_once(live, rec.deps(), state, from_ms(T + 30 * MIN + 2_000), log))  # the next close is not due yet (delay)
    assert len(rec.ticks) == 1 and state.done_through_ms == T + 15 * MIN
    run(poll_once(live, rec.deps(), state, from_ms(T + 30 * MIN + 6_000), log))
    assert len(rec.ticks) == 2 and state.done_through_ms == T + 30 * MIN
    assert rec.sent == 4 and state.telegram_update_id == 4  # outbox drained and commands polled on every poll


def test_a_tick_that_did_not_reach_the_due_close_is_retried(tmp_path):
    rec, live, state = Recorder(through_lag=15 * MIN), LiveConfig(), LoopState()
    run(poll_once(live, rec.deps(), state, from_ms(T + 15 * MIN + 10_000), tmp_path / "l"))
    run(poll_once(live, rec.deps(), state, from_ms(T + 15 * MIN + 30_000), tmp_path / "l"))
    assert len(rec.ticks) == 2  # Binance had not published the last minute yet: try again next poll


def test_stale_alert_once_and_error_alert_after_three_failures(tmp_path):
    rec = Recorder(statuses=["stale", "stale", "ok", "raise", "raise", "raise", "raise"])
    live, state = LiveConfig(), LoopState()
    for k in range(7):
        status, _ = run(poll_once(live, rec.deps(), state, from_ms(T + 15 * MIN + 10_000 + k * 1000), tmp_path / "l"))
        if k == 2:
            state.done_through_ms = None  # force another tick for the test
    titles = [t for _, t in rec.system]
    assert titles.count("market data stale") == 1 and titles.count("repeated errors") == 1
    assert status == "error"


def test_legacy_paper_run_once_per_hour_and_daily_summary_not_at_first_start(tmp_path):
    rec, live, state = Recorder(), LiveConfig(), LoopState()
    for t in (T + 10_000, T + 20 * MIN, T + H + 10_000):
        run(poll_once(live, rec.deps(), state, from_ms(t), tmp_path / "l"))
    assert len(rec.legacy) == 2
    assert rec.daily == []  # the first run only records today's date
    day_start = (T // 86_400_000 + 1) * 86_400_000
    run(poll_once(live, rec.deps(), state, from_ms(day_start + 10_000), tmp_path / "l"))
    run(poll_once(live, rec.deps(), state, from_ms(day_start + 20_000), tmp_path / "l"))
    assert rec.daily == [from_ms(day_start).date().isoformat()]
    no_legacy = LiveConfig(run_legacy_paper=False)
    rec2 = Recorder()
    run(poll_once(no_legacy, rec2.deps(), LoopState(), from_ms(T + 10_000), tmp_path / "l"))
    assert rec2.legacy == []


def test_forever_writes_heartbeat_and_state_and_resumes(tmp_path, make_config):
    app = make_config()
    rec = Recorder()
    times = iter([from_ms(T + 15 * MIN + 10_000 + k * 1000) for k in range(10)])
    live = LiveConfig(poll_seconds=1)
    run(run_live_forever(app, live, rec.deps(), now_fn=lambda: next(times), max_iterations=2))
    hb = read_heartbeat(app.data.data_dir / "live" / "heartbeat.json")
    assert hb["status"] == "idle" and hb["last_tick_ms"] is not None
    assert [t for _, t in rec.system] == ["live loop started"]
    state = LoopState.load(app.data.data_dir / "live" / "state.json")
    assert state.done_through_ms == T + 15 * MIN
    run(run_live_forever(app, live, rec.deps(), now_fn=lambda: next(times), max_iterations=1))
    assert len(rec.ticks) == 1  # restarted: the already-evaluated close is not evaluated again


def test_stop_event_ends_the_loop(tmp_path, make_config):
    app = make_config()
    rec = Recorder()

    async def main():
        stop = asyncio.Event()
        stop.set()
        await run_live_forever(app, LiveConfig(poll_seconds=60), rec.deps(), now_fn=lambda: from_ms(T + 10_000), stop_event=stop)

    run(main())
    assert rec.ticks == []


def test_event_reminder_once_per_release_inside_its_lead_time(tmp_path):
    from arven.core.macro_config import MacroEvent

    ev = MacroEvent(T + 2 * H, "FOMC", "")
    got: list = []
    rec, live, state = Recorder(), LiveConfig(), LoopState()
    deps = rec.deps(queue_event_reminder=got.append, macro_events=(ev,))
    run(poll_once(live, deps, state, from_ms(T + 59 * MIN), tmp_path / "l"))  # 61 min before: not yet
    assert got == []
    for t in (T + H, T + H + 30 * MIN, T + 2 * H - MIN):
        run(poll_once(live, deps, state, from_ms(t), tmp_path / "l"))
    assert got == [ev] and state.extra["event_reminders"] == [f"FOMC:{ev.scheduled_at_ms}"]
    run(poll_once(LiveConfig(telegram={"event_reminder_minutes": None}), deps, LoopState(), from_ms(T + H + MIN), tmp_path / "l"))
    assert got == [ev]  # switched off


def test_data_is_refreshed_every_minute_between_closes_without_running_strategies(tmp_path):
    """2026-10-27: fresh 1m data once a minute (charts, data age); strategies still run only at 15m closes; a failing
    feed is logged, never raised; data_refresh_seconds: null switches it off."""
    import json

    rec, live, state = Recorder(), LiveConfig(), LoopState()
    log = tmp_path / "log.jsonl"
    calls = []
    deps = rec.deps(refresh_data=lambda now: calls.append(now) or {})
    for sec in (10, 30, 50, 75, 95, 140):  # seconds after a 15m close + 1 minute
        run(poll_once(live, deps, state, from_ms(T + 16 * MIN + sec * 1000), log))
    assert len(calls) == 3 and len(rec.ticks) == 1  # at +10 s, +75 s, +140 s; one tick for the one due close
    failing = rec.deps(refresh_data=lambda now: {"ETHUSDT": "HTTP 503"})
    run(poll_once(live, failing, LoopState(), from_ms(T + 16 * MIN), log))
    assert any(json.loads(x).get("event") == "data_refresh" and "ETHUSDT" in json.loads(x)["detail"] for x in log.read_text().splitlines())
    off, n = LiveConfig(data_refresh_seconds=None), []
    run(poll_once(off, rec.deps(refresh_data=lambda now: n.append(now) or {}), LoopState(), from_ms(T + 16 * MIN), log))
    assert n == []


def test_a_long_poll_keeps_the_heartbeat_alive(tmp_path, make_config, monkeypatch):
    """2026-10-27: a catch-up poll after sleep ran for minutes and the web app said "pulse stale" for a live process;
    now the heartbeat says "working" every PULSE_SECONDS while a poll runs, then the poll's own status."""
    import time as _time

    import arven.live.loop as loop

    app = make_config()
    rec = Recorder()
    seen = []
    real = loop.write_heartbeat
    monkeypatch.setattr(loop, "PULSE_SECONDS", 0.05)
    monkeypatch.setattr(loop, "write_heartbeat", lambda path, **kw: seen.append(kw["status"]) or real(path, **kw))
    deps = rec.deps(live_tick=lambda now: _time.sleep(0.4) or FakeOut("ok", due_close_ms(int(now.timestamp() * 1000), 5_000)))
    run(run_live_forever(app, LiveConfig(poll_seconds=1), deps, now_fn=lambda: from_ms(T + 15 * MIN + 10_000), max_iterations=1))
    assert seen.count("working") >= 3 and seen[-1] == "ok"
