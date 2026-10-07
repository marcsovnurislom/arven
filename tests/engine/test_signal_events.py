import pytest

from arven.engine.signal_events import SignalUpdate, SignalUpdateKind


def test_valid_update_constructs():
    u = SignalUpdate("abc123", 1000, SignalUpdateKind.TP_HIT, "level=TP1;fraction=0.5")
    assert u.signal_id == "abc123" and u.kind == SignalUpdateKind.TP_HIT


def test_rejects_empty_signal_id():
    with pytest.raises(ValueError):
        SignalUpdate("", 1000, SignalUpdateKind.CLOSED, "x")


def test_to_dict_is_json_safe():
    import json

    u = SignalUpdate("abc123", 1000, SignalUpdateKind.STOP_MOVED, "new_stop=100.0")
    d = u.to_dict()
    json.dumps(d)
    assert d == {"signal_id": "abc123", "time_ms": 1000, "kind": "STOP_MOVED", "detail": "new_stop=100.0"}
