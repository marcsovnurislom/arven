"""Dollar account replay: hand-computed sizes and P&L."""

from __future__ import annotations

import pytest

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account, summarize_account


def test_one_percent_risk_rounded_down_to_the_lot_step():
    # $1000 * 1 % = $10 risk; stop $300 away -> 0.0333 BTC -> 0.03 BTC (risk $9); +2 R -> +$18
    (s,) = replay_account([TradeForAccount(300.0, 2.0)])
    assert s.size == pytest.approx(0.03) and s.risk_usd == pytest.approx(9.0)
    assert s.pnl_usd == pytest.approx(18.0) and s.equity_after == pytest.approx(1018.0)


def test_equity_compounds_from_trade_to_trade():
    steps = replay_account([TradeForAccount(100.0, -1.0), TradeForAccount(100.0, 1.0)])
    # 1: $10 / 100 = 0.10 BTC, -1 R = -$10 -> $990; 2: $9.90 / 100 = 0.099 -> 0.09 BTC, +1 R = +$9 -> $999
    assert [s.size for s in steps] == pytest.approx([0.10, 0.09])
    assert steps[-1].equity_after == pytest.approx(999.0)


def test_minimum_lot_is_used_while_its_stop_loss_stays_within_five_percent():
    # stop $2000 away: 1 % ($10) would be 0.005 BTC < 0.01 min lot; 0.01 lot loses $20 = 2 % <= 5 % -> taken at 0.01
    (s,) = replay_account([TradeForAccount(2000.0, -1.0)])
    assert s.size == pytest.approx(0.01) and s.pnl_usd == pytest.approx(-20.0) and s.skipped is None
    # stop $6000 away: 0.01 lot would lose $60 = 6 % > 5 % -> skipped, equity unchanged
    (s,) = replay_account([TradeForAccount(6000.0, 3.0)])
    assert s.skipped == "min_lot_risk_above_limit" and s.size == 0 and s.equity_after == 1000.0


def test_summary_counts_and_drawdown():
    rules = AccountRules()
    steps = replay_account([TradeForAccount(100.0, 1.0), TradeForAccount(100.0, -2.0), TradeForAccount(6000.0, 1.0)], rules)
    # +$10 -> 1010; 0.10 BTC (10.10/100 -> 0.101 -> 0.10) * -2 R * 100 = -$20 -> 990; third skipped
    m = summarize_account(steps, rules)
    assert m["final_equity"] == pytest.approx(990.0) and m["trades"] == 2 and m["skipped"] == 1
    assert m["wins"] == 1 and m["losses"] == 1
    assert m["max_drawdown"] == pytest.approx(20.0 / 1010.0)
