"""Per-regime breakdown: hand-built fixtures."""

import math

from arven.backtest.engine import BacktestResult
from arven.backtest.types import EquityKind, EquityPoint, ExitReason, Trade
from arven.core.types import Action
from arven.decision.engine import ProposedDecision
from arven.decision.pipeline import DecisionRecord
from arven.reports import per_regime_breakdown, regime_at_entry
from arven.regime.detector import Regime, TrendState, VolState

HOUR = 3_600_000
UP = Regime(TrendState.UP, VolState.NORMAL, False, True)
DOWN = Regime(TrendState.DOWN, VolState.NORMAL, False, True)


def rec(t, regime):
    p = ProposedDecision(t, Action.NO_TRADE, 0.0, 0.0, (), (), (), regime, None, None, None, ())
    return DecisionRecord(t, regime, (), p, None)


def trade(signal_ms, net_pnl, r=1.0):
    return Trade(1, 1, signal_ms, signal_ms, signal_ms + HOUR, 1, 1, 1, 1, 0.1, 100, 100, 33, 10_000, ExitReason.TIME_STOP, net_pnl, 0, 0, 0, 0, net_pnl, net_pnl / 10_000, r, 60, 0, 0, "")


def result_with(trades):
    pts = (EquityPoint(0, 10_000, 0, 10_000, 0, 0, EquityKind.FINAL),)
    return BacktestResult("development", 0, 10 * HOUR, 10_000, 10_000, (), (), (), tuple(trades), pts, (), {}, 0, False)


def test_regime_at_entry_looks_up_by_signal_time():
    history = [rec(0, UP), rec(HOUR, DOWN)]
    assert regime_at_entry(history, 0) == "TREND_UP/NORMAL"
    assert regime_at_entry(history, HOUR) == "TREND_DOWN/NORMAL"
    assert regime_at_entry(history, 99) is None


def test_breakdown_groups_trades_by_the_regime_at_signal_time():
    history = [rec(0, UP), rec(HOUR, UP), rec(2 * HOUR, DOWN)]
    trades = [trade(0, 100.0), trade(HOUR, -50.0), trade(2 * HOUR, 30.0)]
    b = per_regime_breakdown(result_with(trades), history)
    assert b["TREND_UP/NORMAL"]["n_trades"] == 2
    assert b["TREND_UP/NORMAL"]["net_pnl_usdt"] == 50.0
    assert b["TREND_UP/NORMAL"]["win_rate"] == 0.5
    assert b["TREND_DOWN/NORMAL"]["n_trades"] == 1 and b["TREND_DOWN/NORMAL"]["net_pnl_usdt"] == 30.0


def test_time_fraction_reflects_regime_persistence_even_without_trades():
    history = [rec(0, UP), rec(HOUR, UP), rec(2 * HOUR, UP), rec(3 * HOUR, DOWN)]
    b = per_regime_breakdown(result_with([]), history)
    assert b["TREND_UP/NORMAL"]["time_fraction"] == 0.75
    assert b["TREND_DOWN/NORMAL"]["time_fraction"] == 0.25
    assert b["TREND_UP/NORMAL"]["n_trades"] == 0 and b["TREND_UP/NORMAL"]["win_rate"] is None


def test_unattributed_trades_are_counted_not_silently_dropped():
    history = [rec(0, UP)]
    b = per_regime_breakdown(result_with([trade(999, 10.0)]), history)
    assert b["_unattributed_trades"]["n_trades"] == 1
    assert b["TREND_UP/NORMAL"]["n_trades"] == 0


def test_avg_r_multiple_ignores_nan():
    history = [rec(0, UP), rec(HOUR, UP)]
    trades = [trade(0, 10.0, r=1.5), trade(HOUR, -10.0, r=math.nan)]
    b = per_regime_breakdown(result_with(trades), history)
    assert b["TREND_UP/NORMAL"]["avg_r_multiple"] == 1.5


def test_format_breakdown_lists_every_regime_and_mentions_unattributed():
    history = [rec(0, UP)]
    from arven.reports import format_breakdown

    b = per_regime_breakdown(result_with([trade(999, 5.0)]), history)
    text = format_breakdown(b)
    assert "TREND_UP/NORMAL" in text and "unattributed trades: 1" in text
