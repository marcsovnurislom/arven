from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, tp_ladder_from_r_multiples
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.engine.signal_store import append_signal, append_update, read_signals, read_updates


def make_signal(event_time_ms=0):
    ladder = tp_ladder_from_r_multiples(((1.0, 1.0),), entry=100.0, stop=98.0, side=1)
    return EngineSignal(
        symbol="BTCUSDT", side=1, strategy_id="s4", strategy_version="v1", grade=Grade.EXPERIMENTAL,
        event_time_ms=event_time_ms, entry_reference=100.0, stop=98.0, tp_ladder=ladder, risk_fraction=0.01,
        confidence=0.7, regime="TREND_UP/NORMAL", reasons=("x",), risk_checks=("ok",),
        versions=SignalVersions("v1", "hash", "abc123"),
    )


def test_read_signals_is_empty_before_anything_is_written(tmp_path):
    assert read_signals(tmp_path, "s4") == []


def test_append_and_read_back_one_signal(tmp_path):
    sig = make_signal()
    append_signal(tmp_path, sig)
    back = read_signals(tmp_path, "s4")
    assert len(back) == 1 and back[0] == sig


def test_signals_from_different_strategies_do_not_mix(tmp_path):
    append_signal(tmp_path, make_signal())
    append_signal(tmp_path, EngineSignal(
        symbol="BTCUSDT", side=1, strategy_id="other", strategy_version="v1", grade=Grade.EXPERIMENTAL,
        event_time_ms=0, entry_reference=100.0, stop=98.0,
        tp_ladder=tp_ladder_from_r_multiples(((1.0, 1.0),), entry=100.0, stop=98.0, side=1),
        risk_fraction=0.01, confidence=0.7, regime="TREND_UP/NORMAL", reasons=(), risk_checks=(),
        versions=SignalVersions("v1", "hash", None),
    ))
    assert len(read_signals(tmp_path, "s4")) == 1
    assert len(read_signals(tmp_path, "other")) == 1


def test_multiple_signals_append_in_order(tmp_path):
    append_signal(tmp_path, make_signal(event_time_ms=0))
    append_signal(tmp_path, make_signal(event_time_ms=3600000))
    back = read_signals(tmp_path, "s4")
    assert [s.event_time_ms for s in back] == [0, 3600000]


def test_read_updates_is_empty_before_anything_is_written(tmp_path):
    assert read_updates(tmp_path, "s4") == []


def test_append_and_read_back_updates(tmp_path):
    sig = make_signal()
    update = SignalUpdate(sig.signal_id, 1000, SignalUpdateKind.TP_HIT, "level=TP1;fraction=1.0")
    append_update(tmp_path, "s4", update)
    back = read_updates(tmp_path, "s4")
    assert back == [update]


def test_a_tampered_stored_signal_is_rejected_on_read(tmp_path):
    append_signal(tmp_path, make_signal())
    path = tmp_path / "s4" / "signals.jsonl"
    import json

    d = json.loads(path.read_text(encoding="utf-8"))
    d["confidence"] = 0.99  # tamper without updating signal_id
    path.write_text(json.dumps(d) + "\n", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError):
        read_signals(tmp_path, "s4")


def test_limit_and_time_exit_signals_round_trip(tmp_path):
    import dataclasses

    from arven.engine.signal_store import append_signal, read_signals

    base = make_signal()
    lim = dataclasses.replace(base, entry_type="limit", valid_until_ms=base.event_time_ms + 3_600_000)
    timed = dataclasses.replace(base, tp_ladder=(), max_holding_minutes=1440)
    append_signal(tmp_path, lim)
    append_signal(tmp_path, timed)
    assert read_signals(tmp_path, base.strategy_id) == [lim, timed]
