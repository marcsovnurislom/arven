"""Signal status shown by the web API for limit entries and time-exit signals (live loop)."""

from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.engine.signal_store import append_signal, append_update
from arven.web.service import list_signals


def _sig(t, **over):
    base = dict(symbol="BTCUSDT", side=1, strategy_id="s7_trend_break_fib", strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=t,
                entry_reference=100.0, stop=99.0, tp_ladder=(TPLevel(1.0, 1.0, 101.0),), risk_fraction=0.01, confidence=0.5, regime="n/a",
                reasons=("x",), risk_checks=(), versions=SignalVersions("v", "h", None), entry_type="limit", valid_until_ms=t + 10_000)
    return EngineSignal(**(base | over))


def test_limit_signal_statuses(tmp_path):
    pending, filled, cancelled = _sig(1000), _sig(2000), _sig(3000)
    timed = _sig(4000, strategy_id="crowded_shorts", tp_ladder=(), max_holding_minutes=1440, entry_type="market", valid_until_ms=None)
    for s in (pending, filled, cancelled, timed):
        append_signal(tmp_path, s)
    append_update(tmp_path, "s7_trend_break_fib", SignalUpdate(filled.signal_id, 2500, SignalUpdateKind.FILLED, "price=100"))
    append_update(tmp_path, "s7_trend_break_fib", SignalUpdate(cancelled.signal_id, 3500, SignalUpdateKind.CANCELLED, "reason=expired"))
    got = {d["event_time_ms"]: d for d in list_signals(tmp_path, ["s7_trend_break_fib", "crowded_shorts"])}
    assert [got[t]["status"] for t in (1000, 2000, 3000, 4000)] == ["pending", "open", "cancelled", "open"]
    assert got[1000]["entry_type"] == "limit" and got[1000]["valid_until_ms"] == 11_000
    assert got[4000]["tp_ladder"] == [] and got[4000]["max_holding_minutes"] == 1440
