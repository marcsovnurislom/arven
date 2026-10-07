from arven.data.storage.db import connect
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, tp_ladder_from_r_multiples
from arven.engine.signal_store import append_signal
from arven.paper.runtime import write_heartbeat
from arven.telegram.commands import HELP_TEXT, WELCOME_TEXT, CommandContext, handle_command
from arven.telegram.outbox import is_paused


def make_signal(strategy_id="s4", event_time_ms=0, grade=Grade.EXPERIMENTAL):
    ladder = tp_ladder_from_r_multiples(((1.0, 1.0),), entry=100.0, stop=98.0, side=1)
    return EngineSignal(
        symbol="BTCUSDT", side=1, strategy_id=strategy_id, strategy_version="v1", grade=grade,
        event_time_ms=event_time_ms, entry_reference=100.0, stop=98.0, tp_ladder=ladder, risk_fraction=0.01,
        confidence=0.7, regime="TREND_UP/NORMAL", reasons=(), risk_checks=(), versions=SignalVersions("v1", "hash", None),
    )


def ctx(tmp_path, now_ms=10_000):
    return CommandContext(con=connect(":memory:"), signals_root=tmp_path / "signals", heartbeat_path=tmp_path / "heartbeat.json", now_ms=now_ms)


def test_start_and_help():
    c = CommandContext(con=connect(":memory:"), signals_root=None, heartbeat_path=None, now_ms=0)
    assert handle_command("/start", "1", c) == WELCOME_TEXT
    assert handle_command("/help", "1", c) == HELP_TEXT


def test_unrecognized_text_returns_none():
    c = CommandContext(con=connect(":memory:"), signals_root=None, heartbeat_path=None, now_ms=0)
    assert handle_command("just chatting", "1", c) is None
    assert handle_command("", "1", c) is None


def test_command_is_case_insensitive_and_strips_bot_username_suffix():
    c = CommandContext(con=connect(":memory:"), signals_root=None, heartbeat_path=None, now_ms=0)
    assert handle_command("/HELP", "1", c) == HELP_TEXT
    assert handle_command("/help@my_arven_bot", "1", c) == HELP_TEXT


def test_status_with_no_heartbeat_yet(tmp_path):
    c = ctx(tmp_path)
    assert "never" in handle_command("/status", "1", c).lower() or "no heartbeat" in handle_command("/status", "1", c).lower()


def test_status_reports_the_real_heartbeat(tmp_path):
    write_heartbeat(tmp_path / "heartbeat.json", status="ticked", checked_at_ms=9_000, last_tick_ms=9_000)
    c = ctx(tmp_path, now_ms=10_000)
    text = handle_command("/status", "1", c)
    assert "status=ticked" in text and "1s ago" in text


def test_status_shows_detail_when_present(tmp_path):
    write_heartbeat(tmp_path / "heartbeat.json", status="error", checked_at_ms=9_000, last_tick_ms=None, detail="REST failed")
    c = ctx(tmp_path, now_ms=10_000)
    assert "REST failed" in handle_command("/status", "1", c)


def test_signals_with_nothing_stored(tmp_path):
    c = ctx(tmp_path)
    assert "No signals" in handle_command("/signals", "1", c)


def test_signals_lists_recent_across_strategies(tmp_path):
    root = tmp_path / "signals"
    append_signal(root, make_signal(strategy_id="a", event_time_ms=1000))
    append_signal(root, make_signal(strategy_id="b", event_time_ms=2000))
    c = ctx(tmp_path)
    text = handle_command("/signals", "1", c)
    assert "BTCUSDT LONG (a)" in text and "BTCUSDT LONG (b)" in text


def test_history_shows_more_than_signals(tmp_path):
    root = tmp_path / "signals"
    for i in range(10):
        append_signal(root, make_signal(strategy_id="a", event_time_ms=i * 1000))
    c = ctx(tmp_path)
    assert len(handle_command("/signals", "1", c).splitlines()) == 5
    assert len(handle_command("/history", "1", c).splitlines()) == 10


def test_strategies_with_nothing_stored(tmp_path):
    c = ctx(tmp_path)
    assert "No strategies" in handle_command("/strategies", "1", c)


def test_strategies_lists_each_with_its_latest_grade(tmp_path):
    root = tmp_path / "signals"
    append_signal(root, make_signal(strategy_id="a", event_time_ms=0, grade=Grade.EXPERIMENTAL))
    append_signal(root, make_signal(strategy_id="a", event_time_ms=1000, grade=Grade.VALIDATED))
    c = ctx(tmp_path)
    text = handle_command("/strategies", "1", c)
    assert "a: 2 signals, current grade VALIDATED" in text


def test_pause_and_resume_toggle_outbox_state(tmp_path):
    c = ctx(tmp_path)
    assert not is_paused(c.con, "chat1")
    reply = handle_command("/pause", "chat1", c)
    assert "paused" in reply.lower()
    assert is_paused(c.con, "chat1")
    reply = handle_command("/resume", "chat1", c)
    assert "resumed" in reply.lower()
    assert not is_paused(c.con, "chat1")
