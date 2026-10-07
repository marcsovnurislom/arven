from arven.data.storage.db import connect
from arven.telegram.outbox import enqueue, get_entry, is_paused, mark_failed, mark_sent, outbox_id, pending_entries, set_paused


def con():
    return connect(":memory:")


def test_enqueue_creates_a_pending_entry():
    c = con()
    oid = enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="hello", now_ms=1000)
    entry = get_entry(c, oid)
    assert entry.status == "pending" and entry.text == "hello" and entry.attempts == 0


def test_enqueue_is_idempotent_for_the_same_signal_event_chat():
    c = con()
    enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="first", now_ms=1000)
    enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="second (ignored)", now_ms=2000)
    assert len(pending_entries(c)) == 1
    assert pending_entries(c)[0].text == "first"


def test_enqueue_is_distinct_per_chat_id():
    c = con()
    enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="a", now_ms=1000)
    enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="2", text="b", now_ms=1000)
    assert len(pending_entries(c)) == 2


def test_outbox_id_is_a_deterministic_hash_of_its_three_keys():
    assert outbox_id("s1", "NEW_SIGNAL", "1") == outbox_id("s1", "NEW_SIGNAL", "1")
    assert outbox_id("s1", "NEW_SIGNAL", "1") != outbox_id("s1", "TP_HIT", "1")


def test_pending_entries_orders_oldest_first():
    c = con()
    enqueue(c, signal_id="s2", event_type="NEW_SIGNAL", chat_id="1", text="second", now_ms=2000)
    enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="first", now_ms=1000)
    assert [e.text for e in pending_entries(c)] == ["first", "second"]


def test_mark_sent_removes_it_from_pending():
    c = con()
    oid = enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="x", now_ms=1000)
    mark_sent(c, oid, telegram_message_id=99, now_ms=2000)
    assert pending_entries(c) == []
    entry = get_entry(c, oid)
    assert entry.status == "sent" and entry.telegram_message_id == 99 and entry.sent_at_ms == 2000 and entry.attempts == 1


def test_mark_failed_stays_pending_until_max_attempts():
    c = con()
    oid = enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="x", now_ms=1000)
    mark_failed(c, oid, error="boom", max_attempts=3)
    entry = get_entry(c, oid)
    assert entry.status == "pending" and entry.attempts == 1 and entry.last_error == "boom"
    mark_failed(c, oid, error="boom", max_attempts=3)
    mark_failed(c, oid, error="boom again", max_attempts=3)
    entry = get_entry(c, oid)
    assert entry.status == "failed" and entry.attempts == 3 and entry.last_error == "boom again"


def test_failed_entries_are_not_retried_by_pending_entries():
    c = con()
    oid = enqueue(c, signal_id="s1", event_type="NEW_SIGNAL", chat_id="1", text="x", now_ms=1000)
    for _ in range(5):
        mark_failed(c, oid, error="boom", max_attempts=1)
    assert pending_entries(c) == []


def test_get_entry_is_none_when_missing():
    c = con()
    assert get_entry(c, "nope") is None


def test_pause_resume_round_trip():
    c = con()
    assert not is_paused(c, "1")
    set_paused(c, "1", True, now_ms=1000)
    assert is_paused(c, "1")
    set_paused(c, "1", False, now_ms=2000)
    assert not is_paused(c, "1")


def test_pause_is_per_chat():
    c = con()
    set_paused(c, "1", True, now_ms=1000)
    assert not is_paused(c, "2")
