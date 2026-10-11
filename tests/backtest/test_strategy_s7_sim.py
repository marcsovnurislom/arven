"""S7 simulator (docs/strategy_s7_trend_break_fib.md sections 3-7): hand-built 1m paths, hand-computed R.

Setup used throughout (long): level 0 = 90, level 1 = 110, deep zone 97.64-100 (fib 0.5 = 100), ATR 2, so the S2 stop
is 89.5 and the targets are 110 / 122.36 / 130. The setup arms at TF bar ``OFF`` (15m bars, 5m lower timeframe) after a
flat warm-up, so TF bar ``OFF + 1`` starts at minute ``M`` = 15 * (OFF + 1).
"""

from __future__ import annotations

import numpy as np
import pytest
from bt_helpers import T0, app_config, make_market, zero_cost_app

from arven.backtest.strategy_s7_sim import S7Bars, make_context, run_setups, simulate_setup
from arven.engine.strategy_s7 import Line, S7Params, S7Setup
from arven.engine.strategy_s7_plan import S7TradeParams

OFF = 30
M = 15 * (OFF + 1)
STOP = 89.5


def aggregate(market, minutes: int) -> S7Bars:
    n = len(market.time_ms) // minutes
    sl = lambda a: a[: n * minutes].reshape(n, minutes)  # noqa: E731
    return S7Bars(
        minutes * 60_000, market.time_ms[: n * minutes : minutes], sl(market.open)[:, 0], sl(market.high).max(axis=1),
        sl(market.low).min(axis=1), sl(market.close)[:, -1], np.ones(n),
    )


def setup(side: int = 1, arm: int = OFF, **kw) -> S7Setup:
    base = dict(
        side=side, line=Line(0, 120.0, -0.1), touches=(1, 2, 3), last_touch=3, h_last=110.0, range_box=None, cross_index=arm - 2,
        break_index=arm - 2, level0_index=arm - 3, level0=90.0, level1_index=arm - 1, level1=110.0, arm_index=arm,
        zone_low=97.64, zone_high=100.0, limit_618=97.64, atr=2.0,
    )
    base.update(kw)
    return S7Setup(**base)


def run(bars: dict, tp: S7TradeParams, costs=None, hours: int = 16, setups=None):
    market = make_market(hours, bars, base_price=105.0, start_ms=T0)
    ctx = make_context(aggregate(market, 15), aggregate(market, 5), market, costs or zero_cost_app().costs, S7Params(), tp)
    return run_setups(ctx, setups or [setup()])


# E1 path: the 5m bar M+5..M+9 reaches 99.5 (zone reached) and closes 101 (back above fib 0.5) -> buy at M+10's open,
# TP1 at M+25, then a drop through the stop at M+45.
E1_PATH = {M + 5: (105.0, 105.0, 99.5, 101.0), M + 25: (101.0, 110.5, 101.0, 110.0), M + 45: (110.0, 110.0, 89.0, 89.0)}


def test_e1_market_entry_tp1_then_stop_zero_costs():
    (out,) = run(E1_PATH, S7TradeParams())
    assert out.status == "trade" and out.entry_time_ms == T0 + (M + 10) * 60_000
    (leg,) = out.legs
    assert leg.entry_price == 101.0 and leg.stop == STOP and leg.reasons == ("TP1", "STOP")
    assert out.net_r == pytest.approx(0.5 * (110 - 101) / 11.5 - 0.5)


def test_e1_with_fees_and_slippage_hand_computed():
    costs = app_config(fees={"taker_fee_bps": 5.0, "maker_fee_bps": 0.0}, slippage={"fixed_bps": 1.0, "volatility_multiplier": 0.0}).costs
    (out,) = run(E1_PATH, S7TradeParams(), costs=costs)
    fill = 101.0 * 1.0001
    risk = fill - STOP
    tp1, stop_exit = 110.0 * 0.9999, STOP * 0.9999
    gross = 0.5 * (tp1 - fill) + 0.5 * (stop_exit - fill)
    fees = 0.5 * tp1 * 0.0005 + 0.5 * stop_exit * 0.0005 + fill * 0.0005
    assert out.legs[0].entry_price == pytest.approx(fill)
    assert out.net_r == pytest.approx((gross - fees) / risk)


# Limit path: the 1m bar M+5 trades down to 97.0 inside TF bar OFF+1 and closes 98 (a big bearish bar through the whole
# zone, so that TF bar's *close* cancels any setup not yet entered), then the full ladder fills.
LIMIT_PATH = {
    M + 5: (105.0, 105.0, 97.0, 98.0), M + 25: (98.0, 110.5, 98.0, 110.0),
    M + 55: (110.0, 122.5, 110.0, 122.0), M + 65: (122.0, 130.5, 122.0, 130.0),
}


def test_e2_limit_fills_inside_the_bar_whose_close_would_cancel_it():
    (out,) = run(LIMIT_PATH, S7TradeParams(entry="E2"))
    assert out.status == "trade" and out.entry_time_ms == T0 + (M + 5) * 60_000
    risk = 97.64 - STOP
    assert out.legs[0].reasons == ("TP1", "TP2", "TP3")
    assert out.net_r == pytest.approx((0.5 * (110 - 97.64) + 0.3 * (122.36 - 97.64) + 0.2 * (130 - 97.64)) / risk)


def test_e1_on_the_same_path_is_cancelled_at_that_close():
    (out,) = run(LIMIT_PATH, S7TradeParams(entry="E1"))
    assert out.status == "cancelled:zone_broken_by_impulse"


def test_an_e1_trigger_at_a_tf_close_yields_to_that_closes_cancellation():
    # zone reached at M+5 (close 98, below fib 0.5); the last 5m bar of TF bar OFF+1 closes 101 -> E1 would buy at M+15,
    # but that same close also completes a big bearish TF bar through the zone (open 105, low 97)
    path = {M + 5: (105.0, 105.0, 97.0, 98.0), M + 14: (98.0, 101.0, 98.0, 101.0)}
    (out,) = run(path, S7TradeParams(entry="E1"))
    assert out.status == "cancelled:zone_broken_by_impulse"


def test_limit_fill_bar_that_also_touches_the_stop_is_a_full_loss():
    (out,) = run({M + 5: (105.0, 105.0, 89.0, 95.0)}, S7TradeParams(entry="E2"))
    assert out.status == "trade" and out.legs[0].reasons == ("STOP",)
    assert out.net_r == pytest.approx(-1.0)


def test_limit_needs_to_trade_through_by_the_spread():
    costs = app_config(fees={"taker_fee_bps": 0.0, "maker_fee_bps": 0.0}, slippage={"fixed_bps": 1.0, "volatility_multiplier": 0.0}).costs
    touch_only = {M + 5: (105.0, 105.0, 97.64, 98.0)}  # touches 97.64 but not 97.64 * (1 - 1 bp)
    (out,) = run(touch_only, S7TradeParams(entry="E2"), costs=costs)
    assert out.status != "trade"


def test_e4_both_halves_fill_and_each_is_weighted_half():
    (out,) = run(LIMIT_PATH, S7TradeParams(entry="E4"))
    assert out.status == "trade" and [leg.entry_price for leg in out.legs] == [100.0, 97.64]
    def ladder(fill: float) -> float:
        return (0.5 * (110 - fill) + 0.3 * (122.36 - fill) + 0.2 * (130 - fill)) / (fill - STOP)
    assert out.net_r == pytest.approx(0.5 * ladder(100.0) + 0.5 * ladder(97.64))


def test_s3_exits_at_the_next_open_after_a_close_below_level0():
    # E1 buy at 101 (M+10); TF bar OFF+3 (minutes M+30..M+44) closes at 89.2 < 90 without touching the 88 hard stop
    path = {M + 5: (105.0, 105.0, 99.5, 101.0), M + 35: (101.0, 101.0, 89.0, 89.2)}
    (out,) = run(path, S7TradeParams(stop="S3"))
    assert out.status == "trade" and out.legs[0].reasons == ("TIME_STOP",)
    assert out.legs[0].exit_time_ms == T0 + (M + 45) * 60_000
    assert out.net_r == pytest.approx((89.2 - 101.0) / (101.0 - 88.0))


def test_min_r_variant_skips_a_trade_whose_tp1_is_too_close():
    (out,) = run(E1_PATH, S7TradeParams(min_tp1_r=1.0))  # TP1 is 9 / 11.5 = 0.78 R away
    assert out.status == "skipped:tp1_below_min_r"


def test_breakeven_after_tp1():
    (out,) = run(E1_PATH, S7TradeParams(breakeven_after_tp1=True))
    assert out.legs[0].reasons == ("TP1", "STOP_BREAKEVEN")
    assert out.net_r == pytest.approx(0.5 * (110 - 101) / 11.5)


def test_short_is_the_mirror_of_the_long():
    mirror = {k: (200 - o, 200 - lo, 200 - h, 200 - c) for k, (o, h, lo, c) in LIMIT_PATH.items()}
    short = setup(side=-1, h_last=90.0, level0=110.0, level1=90.0, zone_low=100.0, zone_high=102.36, limit_618=102.36)
    market = make_market(16, mirror, base_price=95.0, start_ms=T0)
    ctx = make_context(aggregate(market, 15), aggregate(market, 5), market, zero_cost_app().costs, S7Params(), S7TradeParams(entry="E2"))
    (out,) = run_setups(ctx, [short])
    (ref,) = run(LIMIT_PATH, S7TradeParams(entry="E2"))
    assert out.status == "trade" and out.net_r == pytest.approx(ref.net_r)


def test_expires_after_three_times_the_break_to_arm_duration():
    (out,) = run({}, S7TradeParams(entry="E2"))  # price never comes back to the zone
    assert out.status == "expired"


def test_one_trade_at_a_time_a_setup_triggering_inside_an_open_trade_is_busy():
    # a second long setup armed at TF bar OFF+2 (known at M+30) with its 0.618 limit at 110.5: price sits at 110 from M+25,
    # so the limit would fill at M+30 - while the first trade (filled M+5, closed at TP3 at M+65) is still open
    second = setup(arm=OFF + 2, level0=100.0, level1=120.0, zone_low=110.5, zone_high=112.0, limit_618=110.5)
    alone = run(LIMIT_PATH, S7TradeParams(entry="E2"), setups=[second])
    # alone it fills at M+30 and is still open when the data ends (TP2 132.36 never reached): unresolved, not a trade
    assert alone[0].status == "unresolved" and alone[0].entry_time_ms == T0 + (M + 30) * 60_000
    outs = run(LIMIT_PATH, S7TradeParams(entry="E2"), setups=[setup(), second])
    assert [o.status for o in outs] == ["trade", "busy"]


def test_simulate_setup_ignores_bars_before_the_arming_close():
    # the zone is reached and left *inside* the arming bar (minutes before M): no entry may come from it
    path = {M - 10: (105.0, 105.0, 97.0, 105.0)}
    market = make_market(16, path, base_price=105.0, start_ms=T0)
    ctx = make_context(aggregate(market, 15), aggregate(market, 5), market, zero_cost_app().costs, S7Params(), S7TradeParams(entry="E2"))
    assert simulate_setup(ctx, setup(), 0).status == "expired"


# --- trade management variants (owner, 2026-10-11) ---


def test_ladder_moves_the_stop_to_entry_after_tp1():
    # E1 buy at 101, TP1 110 at M+25 (half out), then the drop to 89 exits the other half at the entry (breakeven), not at 89.5
    (out,) = run(E1_PATH, S7TradeParams(management="LADDER"))
    assert out.legs[0].reasons == ("TP1", "STOP_BREAKEVEN")
    assert out.net_r == pytest.approx(0.5 * 9 / 11.5)


def test_runner_holds_the_last_tenth_to_fib3_with_the_stop_at_tp2():
    # E2 at 97.64: TP1 110 (50 %), TP2 122.36 (30 %), fib 2.0 = 130 (10 %); then a fall to 100 stops the runner at TP2 = 122.36
    path = dict(LIMIT_PATH) | {M + 80: (130.0, 130.0, 100.0, 100.0)}
    (out,) = run(path, S7TradeParams(entry="E2", management="RUNNER"))
    assert out.legs[0].reasons == ("TP1", "TP2", "TP3", "STOP_TRAIL")
    risk = 97.64 - STOP
    assert out.net_r == pytest.approx((0.5 * (110 - 97.64) + 0.3 * (122.36 - 97.64) + 0.1 * (130 - 97.64) + 0.1 * (122.36 - 97.64)) / risk)


def test_pre_breakeven_protects_a_trade_that_nearly_reached_tp1():
    # E1 buy at 101 (TP1 110): price reaches 107.5 (> 70 % of the way = 107.3) then collapses -> out at the entry, not at the stop
    path = {M + 5: (105.0, 105.0, 99.5, 101.0), M + 25: (101.0, 107.5, 101.0, 107.0), M + 45: (107.0, 107.0, 89.0, 89.0)}
    assert run(path, S7TradeParams())[0].net_r == pytest.approx(-1.0)
    (out,) = run(path, S7TradeParams(management="PRE_BE_LADDER"))
    assert out.legs[0].reasons == ("STOP_BREAKEVEN",) and out.net_r == pytest.approx(0.0)
