"""Hand-computed accounting cases.

Every expected number below is derived by hand from the equations in ``arven/backtest/accounting.py``.
Unless stated, the market is flat at 30 000 (zero bar range), leverage 3, mmr 0.4%, lot 0.001 BTC, min notional 100.
"""

import math

import pytest
from bt_helpers import (
    FUNDING_INTERVAL,
    HOUR,
    T0,
    app_config,
    bt_config,
    flat_bar,
    long_signal,
    make_market,
    run,
    short_signal,
)

from arven.backtest.types import ExitReason
from arven.core.signal import Signal
from arven.core.types import Action

REAL_COSTS = app_config()  # 5 bps taker, 1 bp fixed slippage, 0.1 x range


def only_trade(res):
    assert len(res.trades) == 1, [t.exit_reason for t in res.trades]
    return res.trades[0]


def test_worked_example_long_take_profit_with_fees_and_slippage():
    # Entry at the open of minute 60 (decision at T0+1h). E=10 000, f=0.5, fixed slippage 1 bp, 5 bp taker fee.
    bars = {60 + 5: (30_000.0, 30_700.0, 30_000.0, 30_600.0)}  # touches TP 30 603.06 on this bar; range 700/30000
    market = make_market(3, bars)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5, stop_pct=0.01, take_profit_pct=0.02)}, app=REAL_COSTS)
    t = only_trade(res)
    p_e = 30_000.0 * (1 + 1e-4)  # entry bar (minute 60) is flat: range 0 -> slippage = fixed 1 bp
    assert t.entry_price == pytest.approx(30_003.0)
    q = math.floor(0.5 * 10_000 / p_e / 0.001) * 0.001
    assert t.qty == pytest.approx(0.166) and q == pytest.approx(0.166)
    assert t.notional_entry == pytest.approx(4_980.498)
    assert t.margin == pytest.approx(4_980.498 / 3)
    ref_x = 30_003.0 * 1.02  # take-profit level 30 603.06
    assert t.exit_ref_price == pytest.approx(30_603.06)
    # Exit bar range = 700 / 30 000 = 233.33 bps -> sigma_x = (1 + 0.1 * 233.333...) bps = 24.3333 bps
    sigma_x = (1.0 + 0.1 * 1e4 * 700.0 / 30_000.0) / 1e4
    p_x = ref_x * (1 - sigma_x)
    assert t.exit_price == pytest.approx(p_x, rel=1e-12)
    fee_e, fee_x = 0.0005 * 4_980.498, 0.0005 * 0.166 * p_x
    price_pnl = 0.166 * (p_x - 30_003.0)
    assert t.fees == pytest.approx(fee_e + fee_x)
    assert t.net_pnl == pytest.approx(price_pnl - fee_e - fee_x, rel=1e-12)
    assert t.exit_reason == ExitReason.TAKE_PROFIT
    assert t.gross_pnl == pytest.approx(0.166 * (ref_x - 30_000.0))
    assert t.gross_pnl - t.slippage_cost - t.fees + t.funding == pytest.approx(t.net_pnl, rel=1e-12)
    assert res.final_wallet == pytest.approx(10_000 + t.net_pnl, rel=1e-12)


def test_worked_example_frictionless_numbers_from_the_plan():
    # Same trade with a zero-range exit bar: the plan's illustrative numbers (P_x = 30 599.999694, net = 94.071900229398).
    # a flat bar exactly at the take-profit level: zero range, so exit slippage is only the fixed 1 bp
    bars = {65: (30_603.06, 30_603.06, 30_603.06, 30_603.06)}
    market = make_market(3, bars)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5, stop_pct=0.01, take_profit_pct=0.02)}, app=REAL_COSTS)
    t = only_trade(res)
    assert t.exit_price == pytest.approx(30_599.999694, abs=1e-9)
    assert t.net_pnl == pytest.approx(94.071900229398, abs=1e-9)
    assert res.final_wallet == pytest.approx(10_094.071900229398, abs=1e-9)


def test_liquidation_price_formula_long_and_short():
    from arven.backtest.margin import liquidation_price

    assert liquidation_price(1, 30_003.0, 3.0, 0.004) == pytest.approx(30_003.0 * (2 / 3) / 0.996)
    assert liquidation_price(-1, 30_000.0, 3.0, 0.004) == pytest.approx(30_000.0 * (4 / 3) / 1.004)


def test_short_stop_out_with_zero_costs():
    # Short 0.5 f: q = floor(5000/30000/0.001)*0.001 = 0.166; stop 1% above entry -> 30 300.
    bars = {70: (30_000.0, 30_310.0, 30_000.0, 30_200.0)}
    market = make_market(3, bars)
    res = run(market, {T0 + HOUR: short_signal(T0 + HOUR, 0.5, stop_pct=0.01)})
    t = only_trade(res)
    assert t.exit_reason == ExitReason.STOP and t.exit_ref_price == pytest.approx(30_300.0)
    assert t.net_pnl == pytest.approx(0.166 * (30_000.0 - 30_300.0))  # -49.8
    assert t.mae == pytest.approx(0.166 * 310.0) and t.mfe == pytest.approx(0.0)
    assert t.r_multiple == pytest.approx(-1.0)


def test_stop_and_target_in_same_bar_stop_wins():
    bars = {80: (30_000.0, 31_000.0, 29_000.0, 30_000.0)}  # touches both 29 700 (stop) and 30 600 (target)
    market = make_market(3, bars)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5, stop_pct=0.01, take_profit_pct=0.02)})
    assert only_trade(res).exit_reason == ExitReason.STOP


def test_gap_through_stop_fills_at_the_open_not_the_stop():
    bars = {90: (29_500.0, 29_600.0, 29_400.0, 29_450.0)}  # opens below the 29 700 stop
    market = make_market(3, bars)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5, stop_pct=0.01)})
    t = only_trade(res)
    assert t.exit_reason == ExitReason.STOP and t.exit_ref_price == pytest.approx(29_500.0)
    assert t.net_pnl == pytest.approx(0.166 * (29_500.0 - 30_000.0))


def test_take_profit_gap_up_exits_at_the_level_never_better():
    bars = {90: (31_000.0, 31_100.0, 30_900.0, 31_000.0)}
    market = make_market(3, bars)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5, take_profit_pct=0.02)})
    t = only_trade(res)
    assert t.exit_reason == ExitReason.TAKE_PROFIT and t.exit_ref_price == pytest.approx(30_600.0)


def test_time_stop_exits_at_the_open_of_the_first_bar_at_or_after():
    market = make_market(4, {150: (30_100.0, 30_200.0, 30_050.0, 30_150.0)})  # minute 150 = T0+2h30m
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5, max_holding_minutes=90)})
    t = only_trade(res)
    assert t.exit_reason == ExitReason.TIME_STOP
    assert t.exit_time_ms == T0 + 150 * 60_000 and t.exit_ref_price == pytest.approx(30_100.0)
    assert t.minutes_held == pytest.approx(90.0)


def test_signal_close_fills_at_the_next_open():
    market = make_market(4, {121: (30_200.0, 30_250.0, 30_150.0, 30_200.0)})
    signals = {
        T0 + HOUR: long_signal(T0 + HOUR, 0.5),
        T0 + 2 * HOUR: Signal(T0 + 2 * HOUR, Action.NO_TRADE, close_position=True),
    }
    res = run(market, signals)
    t = only_trade(res)
    assert t.exit_reason == ExitReason.SIGNAL_CLOSE and t.exit_time_ms == T0 + 2 * HOUR  # open of the bar at t
    assert res.signal_counts["close"] == 1


def test_end_of_period_closes_at_the_last_bar_close_with_costs():
    market = make_market(3, {179: (30_000.0, 30_500.0, 29_900.0, 30_400.0)})
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5)}, app=REAL_COSTS)
    t = only_trade(res)
    assert t.exit_reason == ExitReason.END_OF_PERIOD and t.exit_time_ms == T0 + 3 * HOUR
    assert t.exit_ref_price == pytest.approx(30_400.0)
    sigma_x = (1.0 + 0.1 * 1e4 * 600.0 / 30_000.0) / 1e4
    assert t.exit_price == pytest.approx(30_400.0 * (1 - sigma_x))
    assert res.trades[-1] is t and res.equity[-1].kind.value == "FINAL" and res.equity[-1].qty == 0.0


def test_funding_long_pays_positive_rate_short_receives():
    rate = 0.0001
    rates = {T0 + FUNDING_INTERVAL: rate}
    # Position open across the +8h funding time.
    market = make_market(12, funding_rates=rates)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5)})
    (fe,) = res.funding
    assert fe.time_ms == T0 + FUNDING_INTERVAL and fe.price == pytest.approx(30_000.0)
    assert fe.cash_flow == pytest.approx(-0.166 * 30_000.0 * rate)  # -0.4980
    assert only_trade(res).funding == pytest.approx(fe.cash_flow)
    res_s = run(market, {T0 + HOUR: short_signal(T0 + HOUR, 0.5)})
    assert res_s.funding[0].cash_flow == pytest.approx(+0.166 * 30_000.0 * rate)


def test_funding_boundaries_entry_at_the_funding_instant_is_not_charged_exit_is():
    rates = {T0 + FUNDING_INTERVAL: 0.0001, T0 + 2 * FUNDING_INTERVAL: 0.0001}
    market = make_market(20, funding_rates=rates)
    # Enter exactly at the first funding time (decision at +8h fills at the open of that bar): no payment for it.
    t_entry = T0 + FUNDING_INTERVAL
    res = run(market, {t_entry: long_signal(t_entry, 0.5, max_holding_minutes=8 * 60)})
    trade = only_trade(res)
    assert trade.entry_time_ms == t_entry and trade.exit_time_ms == t_entry + FUNDING_INTERVAL
    # Exit at the open of the bar at the second funding time: that funding IS charged.
    assert [f.time_ms for f in res.funding] == [T0 + 2 * FUNDING_INTERVAL]


def test_missing_funding_rate_raises_by_default_and_uses_assumed_rate_when_configured():
    from arven.backtest.errors import DataError

    market = make_market(12, funding_rates={})  # no funding row at +8h
    with pytest.raises(DataError, match="missing funding rate"):
        run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5)})
    app = app_config(
        fees={"taker_fee_bps": 0.0, "maker_fee_bps": 0.0},
        slippage={"fixed_bps": 0.0, "volatility_multiplier": 0.0},
        funding={"missing_policy": "assume_rate", "assumed_rate_bps": 1.0},
    )
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5)}, app=app)
    assert res.funding[0].rate_assumed and res.funding[0].cash_flow == pytest.approx(-0.166 * 30_000.0 * 1e-4)


def test_liquidation_long_loses_the_isolated_margin():
    # Entry 30 000 (zero costs), L=3: LP = 30 000 * (2/3) / 0.996 = 20 080.32; a wick below it liquidates.
    market = make_market(3, {100: (30_000.0, 30_000.0, 19_000.0, 25_000.0)})
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 1.0)})
    t = only_trade(res)
    margin = t.notional_entry / 3
    assert t.exit_reason == ExitReason.LIQUIDATION
    assert t.exit_ref_price == pytest.approx(30_000.0 * (2 / 3) / 0.996)
    assert t.net_pnl == pytest.approx(-margin)  # zero fees: the whole isolated margin is lost
    assert res.final_wallet == pytest.approx(10_000.0 - margin)
    assert t.gross_pnl - t.slippage_cost - t.fees + t.funding + t.liquidation_extra_loss == pytest.approx(t.net_pnl)


def test_liquidation_short():
    market = make_market(3, {100: (30_000.0, 41_000.0, 30_000.0, 35_000.0)})
    res = run(market, {T0 + HOUR: short_signal(T0 + HOUR, 1.0)})
    t = only_trade(res)
    assert t.exit_reason == ExitReason.LIQUIDATION and t.exit_ref_price == pytest.approx(30_000.0 * (4 / 3) / 1.004)


def test_stop_between_entry_and_liquidation_is_processed_first():
    market = make_market(3, {100: (30_000.0, 30_000.0, 19_000.0, 25_000.0)})
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 1.0, stop_pct=0.10)})  # stop 27 000 > LP 20 080
    assert only_trade(res).exit_reason == ExitReason.STOP


def test_liquidation_beats_take_profit_in_the_same_bar_and_stop_beyond_liquidation_loses_to_it():
    market = make_market(3, {100: (30_000.0, 33_000.0, 19_000.0, 30_000.0)})
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 1.0, take_profit_pct=0.05)})
    assert only_trade(res).exit_reason == ExitReason.LIQUIDATION
    res2 = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 1.0, stop_pct=0.5)})  # stop 15 000 is beyond LP
    assert only_trade(res2).exit_reason == ExitReason.LIQUIDATION


def test_entry_rejections_each_with_a_reason():
    market = make_market(4)

    def reasons(res):
        last = {}
        for e in res.orders:
            last[e.order_id] = e.reason
        return list(last.values())

    assert reasons(run(market, {T0 + HOUR: long_signal(T0 + HOUR, 3.5)})) == ["exceeds_leverage_cap"]
    assert reasons(run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.005)})) == ["below_min_notional"]  # 50 USDT
    # margin + fee > wallet (with fees; with zero fees margin == wallet would just fit)
    assert reasons(run(market, {T0 + HOUR: long_signal(T0 + HOUR, 3.0)}, app=REAL_COSTS)) == ["insufficient_margin"]
    assert reasons(run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5, stop_pct=0.00005)}, app=REAL_COSTS)) == ["invalid_stop"]
    both = {T0 + HOUR: long_signal(T0 + HOUR, 0.5), T0 + 2 * HOUR: long_signal(T0 + 2 * HOUR, 0.5)}
    assert reasons(run(market, both)) == ["", "position_open"]


def test_qty_rounds_down_to_the_lot_step_and_below_min_notional_is_rejected():
    market = make_market(3)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.1)})  # 1000 / 30000 = 0.0333.. -> 0.033
    assert only_trade(res).qty == pytest.approx(0.033)


def test_missing_fill_bar_cancels_the_order_no_forward_search():
    market = make_market(3, drop_minutes={60})  # the bar at the fill time is missing
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5)})
    assert not res.trades
    assert [e.status.value + ":" + e.reason for e in res.orders] == ["CREATED:", "CANCELLED:no_market_data"]


def test_data_gap_in_position_exits_at_the_first_open_after_the_gap():
    market = make_market(4, {130: (30_500.0, 30_600.0, 30_400.0, 30_550.0)}, drop_minutes={125, 126, 127, 128, 129})
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5)})
    t = only_trade(res)
    assert t.exit_reason == ExitReason.DATA_GAP and t.exit_ref_price == pytest.approx(30_500.0)


def test_one_position_no_pyramiding_and_opposite_signal_is_rejected():
    market = make_market(5)
    sig = {T0 + HOUR: long_signal(T0 + HOUR, 0.5), T0 + 2 * HOUR: short_signal(T0 + 2 * HOUR, 0.5)}
    res = run(market, sig)
    assert len(res.trades) == 1
    assert res.signal_counts["entry"] == 2
    assert any(e.reason == "position_open" for e in res.orders)


def test_no_re_entry_at_the_open_where_a_time_stop_exits():
    market = make_market(6)
    sig = {T0 + HOUR: long_signal(T0 + HOUR, 0.5, max_holding_minutes=60), T0 + 2 * HOUR: long_signal(T0 + 2 * HOUR, 0.5)}
    res = run(market, sig)
    assert len(res.trades) == 1 and res.trades[0].exit_time_ms == T0 + 2 * HOUR
    assert any(e.reason == "position_open" for e in res.orders)


def test_latency_moves_the_fill_bar():
    market = make_market(3, {75: (30_050.0, 30_050.0, 30_050.0, 30_050.0)})
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 0.5)}, cfg=bt_config(latency_minutes=15))
    t = only_trade(res)
    assert t.entry_time_ms == T0 + HOUR + 15 * 60_000 and t.entry_ref_price == pytest.approx(30_050.0)


def test_stress_multiplier_scales_slippage():
    market = make_market(3, {60: (30_000.0, 30_030.0, 30_000.0, 30_000.0)})
    sig = {T0 + HOUR: long_signal(T0 + HOUR, 0.5)}
    normal = only_trade(run(market, sig, app=REAL_COSTS))
    stressed = only_trade(run(market, sig, app=REAL_COSTS, stress=True))
    # entry bar range = 30/30000 = 10 bps -> sigma = (1 + 0.1*10) bps = 2 bps; stress x2 -> 4 bps
    assert normal.entry_price == pytest.approx(30_000.0 * (1 + 2e-4))
    assert stressed.entry_price == pytest.approx(30_000.0 * (1 + 4e-4))


def test_no_trade_keeps_equity_exactly_flat():
    market = make_market(6)
    res = run(market, {})
    assert res.final_wallet == 10_000.0 and not res.trades
    assert all(p.equity == 10_000.0 for p in res.equity)


def test_frictionless_hold_equals_price_arithmetic():
    bars = {i: flat_bar(30_000.0 + i) for i in range(60, 180)}
    market = make_market(3, bars)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 1.0)}, cfg=bt_config(leverage=3.0))
    t = only_trade(res)
    q = math.floor(10_000.0 / 30_060.0 / 0.001) * 0.001  # bar 60 opens at 30 060
    assert t.qty == pytest.approx(q)
    assert res.final_wallet == pytest.approx(10_000.0 + q * (30_179.0 - 30_060.0))


def test_equity_marks_open_position_at_the_last_close_before_the_decision():
    bars = {i: flat_bar(30_000.0 + 100 * (i // 60)) for i in range(0, 240)}  # price steps each hour
    market = make_market(4, bars)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 1.0)})
    decisions = [p for p in res.equity if p.kind.value == "DECISION"]
    assert len(decisions) == 4
    entry_price = 30_100.0
    q = math.floor(10_000.0 / entry_price / 0.001) * 0.001
    # decision at +3h marks at the close of minute 179 = 30 100 + ... = 30 000 + 100*2 = 30 200
    assert decisions[3].unrealized == pytest.approx(q * (30_200.0 - entry_price))
    assert decisions[3].equity == pytest.approx(10_000.0 + q * (30_200.0 - entry_price))
    assert decisions[0].equity == 10_000.0


def test_funding_can_liquidate_when_it_is_debited_from_the_margin():
    # f=1.0 at 30 000 (zero costs): q = 0.333, N = 9 990, margin M = 3 330.
    # Funding rate 33% (absurd on purpose): cash = -0.333 * 30 000 * 0.33 = -3 296.7  ->  margin balance 33.3.
    # New liquidation price = (30 000 - 33.3 / 0.333) / 0.996 = 30 020 > price, so the same open liquidates.
    rates = {T0 + FUNDING_INTERVAL: 0.33}
    market = make_market(10, funding_rates=rates)
    sig = {T0 + HOUR: long_signal(T0 + HOUR, 1.0)}
    res = run(market, sig, cfg=bt_config(liquidation_includes_funding=True))
    t = only_trade(res)
    assert t.exit_reason == ExitReason.LIQUIDATION and t.exit_time_ms == T0 + FUNDING_INTERVAL
    assert t.funding == pytest.approx(-0.333 * 30_000.0 * 0.33)
    assert t.net_pnl == pytest.approx(-3_330.0)  # lost exactly the initial margin (funding was part of it)
    assert res.final_wallet == pytest.approx(10_000.0 - 3_330.0)
    assert t.gross_pnl - t.slippage_cost - t.fees + t.funding + t.liquidation_extra_loss == pytest.approx(t.net_pnl)


def test_without_funding_in_margin_the_same_scenario_is_not_liquidated_and_wallet_goes_negative_later():
    rates = {T0 + FUNDING_INTERVAL: 0.33}
    market = make_market(10, funding_rates=rates)
    res = run(market, {T0 + HOUR: long_signal(T0 + HOUR, 1.0)}, cfg=bt_config(liquidation_includes_funding=False))
    t = only_trade(res)
    assert t.exit_reason == ExitReason.END_OF_PERIOD  # the approved-plan model ignores funding for liquidation
    assert res.final_wallet == pytest.approx(10_000.0 - 3_296.7, abs=1e-6)
