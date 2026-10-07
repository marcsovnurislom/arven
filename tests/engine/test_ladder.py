"""Phase 4 gate: hand-computed R-multiple math for a (partial) TP-ladder exit."""

from __future__ import annotations

import math

import pytest

from arven.engine.ladder import ClosedLeg, resolve_legs


def test_single_full_take_profit_leg_matches_the_planned_r_multiple_before_fees():
    # entry 100, stop 98 -> risk = 2. One leg closes 100% exactly at the 2R level (104).
    leg = ClosedLeg(fraction=1.0, exit_price=104.0, fee=0.0, exit_reason="TP1")
    res = resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=[leg])
    assert res.gross_pnl == pytest.approx(4.0)
    assert res.net_pnl == pytest.approx(4.0)
    assert res.r_multiple == pytest.approx(2.0)
    assert res.fully_closed is True


def test_full_stop_loss_leg_is_minus_one_r_before_fees():
    leg = ClosedLeg(fraction=1.0, exit_price=98.0, fee=0.0, exit_reason="STOP")
    res = resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=[leg])
    assert res.r_multiple == pytest.approx(-1.0)


def test_three_rung_ladder_blends_to_the_fraction_weighted_average_r():
    # entry 100, stop 98 (risk=2). TP1=102 (1R, 50%), TP2=104 (2R, 30%), TP3=106 (3R, 20%).
    # Expected blended R, before fees = 0.5*1 + 0.3*2 + 0.2*3 = 0.5 + 0.6 + 0.6 = 1.7
    legs = [
        ClosedLeg(0.5, 102.0, 0.0, "TP1"),
        ClosedLeg(0.3, 104.0, 0.0, "TP2"),
        ClosedLeg(0.2, 106.0, 0.0, "TP3"),
    ]
    res = resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=legs)
    assert res.gross_pnl == pytest.approx(0.5 * 2 + 0.3 * 4 + 0.2 * 6)  # = 1+1.2+1.2 = 3.4
    assert res.r_multiple == pytest.approx(1.7)
    assert res.fully_closed is True


def test_partial_ladder_then_stop_on_the_remainder():
    # TP1 (1R, 50%) fills, then the remaining 50% stops out at break-even (100, not the original 98).
    # Expected: leg1 gross = 0.5*2 = 1.0 (1R*50%); leg2 gross = 0.5*(100-100) = 0.0.
    # Blended R = (1.0 + 0.0) / risk(2) = 0.5
    legs = [
        ClosedLeg(0.5, 102.0, 0.0, "TP1"),
        ClosedLeg(0.5, 100.0, 0.0, "STOP_BREAKEVEN"),
    ]
    res = resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=legs)
    assert res.gross_pnl == pytest.approx(1.0)
    assert res.r_multiple == pytest.approx(0.5)
    assert res.fully_closed is True


def test_fees_reduce_the_realized_r_multiple():
    # Same single 2R exit as the first test, but with a $0.5 fee (per unit of original size) -> net = 3.5,
    # r = 3.5/2 = 1.75.
    leg = ClosedLeg(fraction=1.0, exit_price=104.0, fee=0.5, exit_reason="TP1")
    res = resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=[leg])
    assert res.net_pnl == pytest.approx(3.5)
    assert res.r_multiple == pytest.approx(1.75)


def test_short_side_mirrors_the_long_math():
    # Short entry 100, stop 102 (risk=2). TP at 96 is 2R in profit for a short.
    leg = ClosedLeg(fraction=1.0, exit_price=96.0, fee=0.0, exit_reason="TP1")
    res = resolve_legs(entry_price=100.0, stop_price=102.0, side=-1, legs=[leg])
    assert res.r_multiple == pytest.approx(2.0)


def test_partial_fill_leaves_fully_closed_false():
    leg = ClosedLeg(fraction=0.5, exit_price=102.0, fee=0.0, exit_reason="TP1")
    res = resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=[leg])
    assert res.fully_closed is False
    assert res.r_multiple == pytest.approx(0.5)  # 0.5 * 1R


def test_legs_summing_to_more_than_one_are_rejected():
    legs = [ClosedLeg(0.7, 102.0, 0.0, "TP1"), ClosedLeg(0.5, 104.0, 0.0, "TP2")]
    with pytest.raises(ValueError):
        resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=legs)


def test_no_legs_is_rejected():
    with pytest.raises(ValueError):
        resolve_legs(entry_price=100.0, stop_price=98.0, side=1, legs=[])


def test_equal_entry_and_stop_is_rejected_zero_risk():
    leg = ClosedLeg(1.0, 104.0, 0.0, "TP1")
    with pytest.raises(ValueError):
        resolve_legs(entry_price=100.0, stop_price=100.0, side=1, legs=[leg])


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.1, math.nan, math.inf])
def test_closed_leg_rejects_invalid_fraction(bad):
    with pytest.raises(ValueError):
        ClosedLeg(bad, 104.0, 0.0, "TP1")


def test_closed_leg_rejects_negative_fee():
    with pytest.raises(ValueError):
        ClosedLeg(1.0, 104.0, -0.01, "TP1")
