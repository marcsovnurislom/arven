from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, tp_ladder_from_r_multiples
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.telegram.messages import (
    DISCLAIMER,
    DailySummarySection,
    TrackRecord,
    format_daily_summary,
    format_new_signal,
    format_signal_update,
    format_system_alert,
)


def make_signal(**over):
    ladder = tp_ladder_from_r_multiples(((1.0, 0.5), (2.0, 0.5)), entry=100.0, stop=98.0, side=1)
    base = dict(
        symbol="BTCUSDT", side=1, strategy_id="s4", strategy_version="v1", grade=Grade.EXPERIMENTAL,
        event_time_ms=0, entry_reference=100.0, stop=98.0, tp_ladder=ladder, risk_fraction=0.01,
        confidence=0.7, regime="TREND_UP/NORMAL", reasons=("ema cross", "adx strong"), risk_checks=("ok",),
        versions=SignalVersions("v1", "hash", "abc123"),
    )
    base.update(over)
    return EngineSignal(**base)


def test_format_new_signal_includes_every_key_fact():
    text = format_new_signal(make_signal())
    assert "BTCUSDT" in text and "LONG" in text
    assert "EXPERIMENTAL" in text
    assert "s4" in text and "v1" in text
    assert "100.00" in text  # entry
    assert "98.00" in text  # stop
    assert "TP1: 102.00 (1.00R, close 50%)" in text
    assert "TP2: 104.00 (2.00R, close 50%)" in text
    assert "Risk: 1.00% of equity (fixed rule, the same for every signal)" in text
    assert "Confidence" not in text and "70%" not in text  # the unvalidated per-signal confidence is never shown
    assert "Quality: no validated per-signal estimate" in text
    assert "Record: not available" in text  # no record passed
    assert "TREND_UP/NORMAL" in text
    assert "ema cross" in text and "adx strong" in text
    assert DISCLAIMER in text


def test_format_new_signal_short_side():
    ladder = tp_ladder_from_r_multiples(((1.0, 1.0),), entry=100.0, stop=102.0, side=-1)
    text = format_new_signal(make_signal(side=-1, entry_reference=100.0, stop=102.0, tp_ladder=ladder))
    assert "SHORT" in text and "LONG" not in text


def test_format_new_signal_caps_reasons_at_three():
    text = format_new_signal(make_signal(reasons=("a", "b", "c", "d", "e")))
    assert "a" in text and "b" in text and "c" in text
    assert "; d" not in text and "; e" not in text


def test_format_new_signal_handles_no_reasons():
    text = format_new_signal(make_signal(reasons=()))
    assert "(none recorded)" in text


def test_format_signal_update_tp_hit():
    signal = make_signal()
    update = SignalUpdate(signal.signal_id, 1000, SignalUpdateKind.TP_HIT, "level=TP1;fraction=0.5;price=102.0")
    text = format_signal_update(signal, update)
    assert "TP hit" in text and "BTCUSDT" in text and "s4" in text
    assert "level=TP1;fraction=0.5;price=102.0" in text
    assert DISCLAIMER in text


def test_format_signal_update_every_kind_has_a_distinct_verb():
    signal = make_signal()
    verbs = set()
    for kind in SignalUpdateKind:
        update = SignalUpdate(signal.signal_id, 1000, kind, "x")
        verbs.add(format_signal_update(signal, update).splitlines()[0])
    assert len(verbs) == len(SignalUpdateKind)


def test_format_system_alert():
    text = format_system_alert("process restarted", "heartbeat was stale for 5 minutes")
    assert "SYSTEM ALERT" in text and "process restarted" in text and "heartbeat was stale" in text


def test_format_daily_summary_with_sections():
    sections = (DailySummarySection("s4", "VALIDATED", 3, 2, 1.25), DailySummarySection("trend_momentum", "EXPERIMENTAL", 1, 0, 0.0))
    text = format_daily_summary("2026-10-08", sections)
    assert "2026-10-08" in text
    assert "s4 [VALIDATED]: 3 signals, 2 closed, net +1.25R" in text
    assert "trend_momentum [EXPERIMENTAL]: 1 signals, 0 closed, net +0.00R" in text
    assert DISCLAIMER in text


def test_format_daily_summary_with_no_sections():
    text = format_daily_summary("2026-10-08", ())
    assert "No signals today." in text


def test_limit_entry_and_time_exit_are_spelled_out():
    lim = format_new_signal(make_signal(entry_type="limit", valid_until_ms=3_600_000))
    assert "Entry: LIMIT 100.00 (valid until 1970-01-01 01:00 UTC)" in lim
    timed = format_new_signal(make_signal(tp_ladder=(), max_holding_minutes=1440))
    assert "No take-profit: time exit after 24 h" in timed and "TP1" not in timed


def test_format_new_signal_shows_the_track_record():
    since = 1_782_864_000_000  # 2026-07-01
    assert "Record (paper since 2026-07-01): no closed signals yet" in format_new_signal(make_signal(), TrackRecord(0, 0, 0.0, since))
    text = format_new_signal(make_signal(), TrackRecord(27, 11, -11.51, since))
    assert "Record (paper since 2026-07-01): 27 closed, win 41%, net -11.51 R" in text
