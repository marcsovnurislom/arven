"""Phase 6 composition roots, end to end against fakes (no sockets) - mirrors tests/news/test_runs.py."""

from __future__ import annotations

import json

from arven.core.telegram_config import TelegramConfig
from arven.core.time import from_ms
from arven.data.storage.db import connect
from arven.telegram.outbox import enqueue, get_entry, set_paused
from arven.telegram.runs import read_update_cursor, run_telegram_commands_tick, run_telegram_send_tick, write_update_cursor

from test_client import ScriptedOpener, ok_response


def cfg(**over) -> TelegramConfig:
    base = {"dry_run": False, "command_poll_timeout_seconds": 0, "max_send_attempts": 3}
    base.update(over)
    return TelegramConfig.model_validate(base)


# --- run_telegram_send_tick ---------------------------------------------------------------------------


def test_dry_run_marks_sent_without_any_network_call():
    con = connect(":memory:")
    oid = enqueue(con, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="x", now_ms=1000)
    summary = run_telegram_send_tick(con, cfg(dry_run=True), opener=ScriptedOpener(), now=from_ms(2000))
    assert summary.sent == 1 and summary.dry_run
    assert get_entry(con, oid).status == "sent"


def test_real_send_marks_sent_with_the_returned_message_id():
    con = connect(":memory:")
    oid = enqueue(con, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="x", now_ms=1000)
    opener = ScriptedOpener(ok_response({"message_id": 77}))
    summary = run_telegram_send_tick(con, cfg(), token="t", opener=opener, sleep=lambda s: None, now=from_ms(2000))
    assert summary.sent == 1 and summary.ok
    entry = get_entry(con, oid)
    assert entry.status == "sent" and entry.telegram_message_id == 77


def test_a_failed_send_is_recorded_and_other_entries_still_get_a_chance():
    con = connect(":memory:")
    enqueue(con, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="first", now_ms=1000)
    enqueue(con, signal_id="s2", event_type="NEW_SIGNAL", chat_id="1", text="second", now_ms=2000)
    import urllib.error

    opener = ScriptedOpener(urllib.error.URLError("boom"), urllib.error.URLError("boom"), urllib.error.URLError("boom"), ok_response({"message_id": 1}))
    summary = run_telegram_send_tick(con, cfg(max_send_attempts=3), token="t", opener=opener, sleep=lambda s: None, now=from_ms(2000))
    assert summary.failed == 1 and summary.sent == 1
    assert not summary.ok and summary.errors


def test_paused_chats_are_skipped_and_stay_pending():
    con = connect(":memory:")
    set_paused(con, "1", True, now_ms=0)
    oid = enqueue(con, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="x", now_ms=1000)
    summary = run_telegram_send_tick(con, cfg(dry_run=True), now=from_ms(2000))
    assert summary.skipped_paused == 1 and summary.sent == 0
    assert get_entry(con, oid).status == "pending"


# --- run_telegram_commands_tick ------------------------------------------------------------------------


def test_replies_to_an_allowed_chat_and_ignores_unrecognised_text(tmp_path):
    con = connect(":memory:")
    opener = ScriptedOpener(
        ok_response([{"update_id": 1, "message": {"message_id": 1, "chat": {"id": 7}, "text": "/help", "date": 0}}]),
        ok_response({"message_id": 100}),  # the reply to /help
    )
    summary, new_id = run_telegram_commands_tick(
        con, cfg(), tmp_path / "signals", tmp_path / "heartbeat.json",
        last_update_id=0, allowed_chats=frozenset({"7"}), token="t", opener=opener, sleep=lambda s: None,
    )
    assert summary.updates_seen == 1 and summary.replied == 1 and summary.unauthorized == 0
    assert new_id == 1


def test_unauthorized_chat_gets_the_not_authorized_reply_not_a_command_reply(tmp_path):
    con = connect(":memory:")
    opener = ScriptedOpener(
        ok_response([{"update_id": 1, "message": {"message_id": 1, "chat": {"id": 666}, "text": "/status", "date": 0}}]),
        ok_response({"message_id": 100}),  # the "not authorized" reply
    )
    summary, new_id = run_telegram_commands_tick(
        con, cfg(), tmp_path / "signals", tmp_path / "heartbeat.json",
        last_update_id=0, allowed_chats=frozenset({"7"}), token="t", opener=opener, sleep=lambda s: None,
    )
    assert summary.unauthorized == 1 and summary.replied == 0
    sent_text = json.loads(opener.calls[1].data)["text"]
    assert "not authorized" in sent_text.lower()


def test_an_unrecognised_command_from_an_allowed_chat_sends_no_reply(tmp_path):
    con = connect(":memory:")
    opener = ScriptedOpener(
        ok_response([{"update_id": 1, "message": {"message_id": 1, "chat": {"id": 7}, "text": "hello there", "date": 0}}]),
    )
    summary, new_id = run_telegram_commands_tick(
        con, cfg(), tmp_path / "signals", tmp_path / "heartbeat.json",
        last_update_id=0, allowed_chats=frozenset({"7"}), token="t", opener=opener, sleep=lambda s: None,
    )
    assert summary.updates_seen == 1 and summary.replied == 0
    assert len(opener.calls) == 1  # only the getUpdates call - no reply was sent


def test_last_update_id_advances_to_the_highest_seen():
    con = connect(":memory:")
    opener = ScriptedOpener(
        ok_response([
            {"update_id": 5, "message": {"message_id": 1, "chat": {"id": 7}, "text": "hi", "date": 0}},
            {"update_id": 9, "message": {"message_id": 2, "chat": {"id": 7}, "text": "hi", "date": 0}},
        ]),
    )
    _, new_id = run_telegram_commands_tick(
        con, cfg(), None, None, last_update_id=0, allowed_chats=frozenset({"7"}), token="t", opener=opener, sleep=lambda s: None,
    )
    assert new_id == 9


def test_a_getupdates_failure_is_recorded_not_raised(tmp_path, monkeypatch):
    """Regression: found via `arven telegram commands` with no TELEGRAM_BOT_TOKEN configured - the real
    client's own TelegramConfigError propagated uncaught and crashed the CLI with a traceback."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    con = connect(":memory:")
    summary, new_id = run_telegram_commands_tick(
        con, cfg(), tmp_path / "signals", tmp_path / "heartbeat.json",
        last_update_id=5, allowed_chats=frozenset({"7"}), opener=ScriptedOpener(), sleep=lambda s: None,
    )
    assert not summary.ok
    assert "getUpdates failed" in summary.errors[0]
    assert new_id == 5  # unchanged: nothing was actually processed


def test_offset_sent_is_last_update_id_plus_one():
    con = connect(":memory:")
    opener = ScriptedOpener(ok_response([]))
    run_telegram_commands_tick(con, cfg(), None, None, last_update_id=41, allowed_chats=frozenset(), token="t", opener=opener, sleep=lambda s: None)
    assert json.loads(opener.calls[0].data)["offset"] == 42


# --- cursor persistence --------------------------------------------------------------------------------


def test_update_cursor_round_trips(tmp_path):
    path = tmp_path / "cursor.json"
    assert read_update_cursor(path) == 0
    write_update_cursor(path, 123)
    assert read_update_cursor(path) == 123
