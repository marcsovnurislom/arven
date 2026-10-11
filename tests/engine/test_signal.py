import pytest

from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel, tp_ladder_from_r_multiples


_MISSING = object()


def make(**over):
    ladder = over.pop("tp_ladder", _MISSING)
    if ladder is _MISSING:
        ladder = tp_ladder_from_r_multiples(((1.0, 0.5), (2.0, 0.5)), entry=100.0, stop=98.0, side=1)
    base = dict(
        symbol="BTCUSDT", side=1, strategy_id="s4", strategy_version="v1", grade=Grade.EXPERIMENTAL,
        event_time_ms=1000, entry_reference=100.0, stop=98.0, tp_ladder=ladder, risk_fraction=0.01,
        confidence=0.7, regime="TREND_UP/NORMAL", reasons=("x",), risk_checks=("ok",),
        versions=SignalVersions("v1", "hash", "abc123"),
    )
    base.update(over)
    return EngineSignal(**base)


def test_tp_level_price_derived_correctly_for_long_and_short():
    long_tp = TPLevel.from_r_multiple(2.0, 0.5, entry=100.0, stop=98.0, side=1)
    assert long_tp.price == pytest.approx(104.0)
    short_tp = TPLevel.from_r_multiple(2.0, 0.5, entry=100.0, stop=102.0, side=-1)
    assert short_tp.price == pytest.approx(96.0)


def test_signal_id_is_deterministic_for_identical_content():
    a, b = make(), make()
    assert a.signal_id == b.signal_id


def test_signal_id_changes_with_any_field():
    base = make().signal_id
    assert make(confidence=0.71).signal_id != base
    assert make(regime="TREND_DOWN/NORMAL").signal_id != base
    assert make(event_time_ms=1001).signal_id != base


def test_r_plan_reads_off_the_ladder():
    sig = make()
    assert sig.r_plan == (1.0, 2.0)


def test_rejects_stop_on_the_wrong_side_for_long():
    with pytest.raises(ValueError):
        make(stop=101.0)  # above entry for a long


def test_rejects_stop_on_the_wrong_side_for_short():
    ladder = tp_ladder_from_r_multiples(((1.0, 1.0),), entry=100.0, stop=102.0, side=-1)
    with pytest.raises(ValueError):
        make(side=-1, stop=99.0, tp_ladder=ladder)  # below entry for a short


def test_rejects_empty_ladder():
    with pytest.raises(ValueError):
        make(tp_ladder=())


def test_rejects_ladder_fractions_summing_above_one():
    ladder = tp_ladder_from_r_multiples(((1.0, 0.7), (2.0, 0.5)), entry=100.0, stop=98.0, side=1)
    with pytest.raises(ValueError):
        make(tp_ladder=ladder)


def test_accepts_ladder_fractions_summing_below_one():
    ladder = tp_ladder_from_r_multiples(((1.0, 0.5),), entry=100.0, stop=98.0, side=1)
    make(tp_ladder=ladder)  # must not raise - the remainder is allowed to run


def test_rejects_ladder_not_ordered_nearest_first():
    ladder = (TPLevel(2.0, 0.5, 104.0), TPLevel(1.0, 0.5, 102.0))
    with pytest.raises(ValueError):
        make(tp_ladder=ladder)


def test_rejects_a_long_take_profit_below_entry():
    bad = (TPLevel(1.0, 1.0, 99.0),)
    with pytest.raises(ValueError):
        make(tp_ladder=bad)


@pytest.mark.parametrize("bad_confidence", [-0.01, 1.01])
def test_rejects_confidence_out_of_range(bad_confidence):
    with pytest.raises(ValueError):
        make(confidence=bad_confidence)


def test_rejects_non_positive_risk_fraction():
    with pytest.raises(ValueError):
        make(risk_fraction=0.0)


def test_rejects_invalid_side():
    with pytest.raises(ValueError):
        make(side=0)


def test_to_dict_round_trips_through_json_safe_types():
    import json

    d = make().to_dict()
    json.dumps(d)  # must not raise
    assert d["tp_ladder"] == [[1.0, 0.5, 102.0], [2.0, 0.5, 104.0]]


def test_empty_ladder_is_allowed_only_with_a_time_exit():
    sig = make(tp_ladder=(), max_holding_minutes=24 * 60)
    assert sig.tp_ladder == () and sig.r_plan == ()
    with pytest.raises(ValueError):
        make(tp_ladder=(), max_holding_minutes=None)


def test_limit_entry_fields_are_hashed_only_when_set():
    market = make()
    assert "entry_type" not in market.to_dict() and "valid_until_ms" not in market.to_dict()
    limit = make(entry_type="limit", valid_until_ms=market.event_time_ms + 60_000)
    assert limit.to_dict()["entry_type"] == "limit" and limit.signal_id != market.signal_id
    with pytest.raises(ValueError):
        make(entry_type="stop")
    with pytest.raises(ValueError):
        make(valid_until_ms=market.event_time_ms)
