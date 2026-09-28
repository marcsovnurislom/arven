"""Metrics against hand-computed values (no ranking or scoring exists to test: only measurements)."""

import math

import numpy as np
import pytest
from bt_helpers import HOUR, T0, Scripted, app_config, bt_config, features_for, long_signal, make_market, window

from arven.backtest.engine import Backtester, BacktestResult
from arven.backtest.metrics import DAY_MS, compute_metrics, daily_equity, drawdown, summarize_distribution
from arven.backtest.types import EquityKind, EquityPoint, ExitReason, FundingEvent, Trade

CFG = bt_config()


def trade(net, *, gross=None, fees=0.0, slip=0.0, funding=0.0, entry=0, exit_=HOUR, reason=ExitReason.TIME_STOP, ne=1000.0, nx=1000.0, margin=333.0, decision_equity=10_000.0):
    gross = net + fees + slip - funding if gross is None else gross
    return Trade(1, 1, entry, entry, exit_, 1.0, 1.0, 1.0, 1.0, 0.1, ne, nx, margin, decision_equity, reason, gross, slip, fees, funding, 0.0, net, net / decision_equity, math.nan, (exit_ - entry) / 60_000, 0.0, 0.0, "")


def result(equities, *, trades=(), funding=(), low_points=(), start=T0, step=HOUR, signal_counts=None, orders=()):
    pts = [EquityPoint(start + i * step, e, 0.0, e, 0.0, 0.0, EquityKind.DECISION) for i, e in enumerate(equities)]
    end = start + len(equities) * step
    pts.append(EquityPoint(end, equities[-1], 0.0, equities[-1], 0.0, 0.0, EquityKind.FINAL))
    return BacktestResult("development", start, end, equities[0], equities[-1], tuple(orders), (), tuple(funding), tuple(trades), tuple(pts), tuple(low_points), signal_counts or {}, len(equities), False)


def test_drawdown_peak_trough_recovery_and_duration():
    r = result([100, 120, 90, 110, 130, 65, 100, 131])
    d = drawdown(r)
    assert d["max_drawdown"] == pytest.approx(0.5)
    assert d["max_drawdown_peak_ms"] == T0 + 4 * HOUR and d["max_drawdown_trough_ms"] == T0 + 5 * HOUR
    assert d["max_drawdown_recovery_ms"] == T0 + 7 * HOUR
    assert d["max_drawdown_duration_days"] == pytest.approx(3 * HOUR / DAY_MS)
    unrecovered = drawdown(result([100, 120, 60, 70]))
    assert unrecovered["max_drawdown_recovery_ms"] is None and unrecovered["max_drawdown"] == pytest.approx(0.5)


def test_intrabar_drawdown_uses_worst_case_lows():
    r = result([100, 100, 100], low_points=[(T0 + 2 * HOUR, 80.0)])
    d = drawdown(r)
    assert d["max_drawdown"] == 0.0 and d["max_intrabar_drawdown"] == pytest.approx(0.2)


def test_daily_series_uses_midnight_decisions_start_and_final():
    eq = [100.0 + i for i in range(72)]  # 72 hourly decisions = 3 days starting at midnight
    t, v = daily_equity(result(eq))
    assert list(t) == [T0, T0 + DAY_MS, T0 + 2 * DAY_MS, T0 + 3 * DAY_MS]
    assert list(v) == [100.0, 124.0, 148.0, 171.0]  # last = FINAL point (equity of the last decision)


def test_volatility_sharpe_sortino_match_numpy_formulas_and_null_rules():
    rng = np.random.default_rng(3)
    daily = 10_000 * np.cumprod(1 + rng.normal(0.001, 0.02, 60))
    eq = np.repeat(daily, 24)  # one equity value per hour, changing at midnight
    m = compute_metrics(result(list(eq)), CFG)
    _, v = daily_equity(result(list(eq)))
    rets = v[1:] / v[:-1] - 1
    ann = math.sqrt(365)
    assert m["volatility"] == pytest.approx(rets.std(ddof=1) * ann)
    assert m["sharpe"] == pytest.approx(rets.mean() / rets.std(ddof=1) * ann)
    down = math.sqrt(np.mean(np.minimum(rets, 0) ** 2))
    assert m["sortino"] == pytest.approx(rets.mean() / down * ann)
    short = compute_metrics(result(list(np.repeat([100.0, 101, 102], 24))), CFG)
    assert short["sharpe"] is None and short["volatility"] is None and short["n_daily_returns"] < 30
    assert any("daily returns" in w for w in short["warnings"])
    flat = compute_metrics(result([100.0] * 24 * 40), CFG)
    assert flat["sharpe"] is None and flat["sortino"] is None  # zero variance


def test_total_return_gross_return_and_cagr_rules():
    m = compute_metrics(result([10_000.0] * 24 * 10 + [11_000.0] * 24 * 10, trades=[trade(1000.0, gross=1150.0, fees=100.0, slip=50.0)]), CFG)
    assert m["total_return"] == pytest.approx(0.1) and m["net_pnl_usdt"] == pytest.approx(1000.0)
    assert m["gross_return"] == pytest.approx(0.115)
    assert m["cagr"] is None  # 20 days < 365
    days = 400
    eq = list(np.linspace(10_000, 20_000, 24 * days))
    m2 = compute_metrics(result(eq), CFG)
    assert m2["cagr"] == pytest.approx((20_000.0 / 10_000.0) ** (365 / days) - 1, rel=1e-3)


def test_trade_statistics_and_costs():
    trades = [trade(300.0, fees=10, slip=5, funding=-2), trade(-100.0, fees=10, slip=5, funding=3), trade(-50.0, fees=10, slip=5), trade(150.0, fees=10, slip=5)]
    funding = [FundingEvent(1, T0, 0.0001, False, 30_000.0, 0.1, -2.0), FundingEvent(1, T0, 0.0001, False, 30_000.0, 0.1, 3.0)]
    m = compute_metrics(result([10_000.0] * 48, trades=trades, funding=funding), CFG)
    assert m["n_trades"] == 4 and m["win_rate"] == 0.5
    assert m["avg_trade_usdt"] == pytest.approx(75.0) and m["avg_win_usdt"] == pytest.approx(225.0) and m["avg_loss_usdt"] == pytest.approx(-75.0)
    assert m["profit_factor"] == pytest.approx(450.0 / 150.0)
    assert m["fees_total"] == 40.0 and m["slippage_total"] == 20.0 and m["funding_total"] == pytest.approx(1.0)
    assert m["funding_paid"] == 2.0 and m["funding_received"] == 3.0
    assert m["traded_notional_usdt"] == 8_000.0 and m["turnover"] == pytest.approx(0.8)
    assert m["exposure_time"] == pytest.approx(4 * 60 / (48 * 60))  # four 1h trades in 48h
    assert m["exit_reasons"] == {"TIME_STOP": 4}
    assert any("only 4 trades" in w for w in m["warnings"])


def test_profit_factor_and_win_rate_are_null_without_the_needed_trades():
    none = compute_metrics(result([10_000.0] * 48), CFG)
    assert none["n_trades"] == 0 and none["win_rate"] is None and none["profit_factor"] is None and none["avg_trade_usdt"] is None
    winners = compute_metrics(result([10_000.0] * 48, trades=[trade(10.0), trade(20.0)]), CFG)
    assert winners["profit_factor"] is None and "no winners or no losers" in winners["profit_factor_undefined_reason"]


def test_liquidation_and_stress_warnings():
    r = result([10_000.0] * 48, trades=[trade(-3_000.0, reason=ExitReason.LIQUIDATION)])
    r = BacktestResult(**{**r.__dict__, "stress": True})
    m = compute_metrics(r, CFG)
    assert m["liquidations"] == 1
    assert any("liquidation" in w for w in m["warnings"]) and any("stress" in w for w in m["warnings"])


def test_distribution_summary_is_descriptive_only():
    d = summarize_distribution([1.0, 2.0, 3.0, 4.0, 5.0])
    assert d["n"] == 5 and d["mean"] == 3.0 and d["min"] == 1.0 and d["max"] == 5.0 and d["p50"] == 3.0
    assert d["std"] == pytest.approx(np.std([1, 2, 3, 4, 5], ddof=1))
    assert summarize_distribution([])["mean"] is None
    assert set(d) == {"n", "mean", "std", "min", "p5", "p50", "p95", "max"}  # no rank / score / best


def test_end_to_end_metrics_from_an_engine_run():
    bars = {60 + i: (30_000.0 + 10 * i, 30_000.0 + 10 * i, 30_000.0 + 10 * i, 30_000.0 + 10 * i) for i in range(180)}
    market = make_market(6, bars)
    win = window(6)
    res = Backtester(app_config(), bt_config(), win, market, features_for(win)).run(Scripted({T0 + HOUR: long_signal(T0 + HOUR, 1.0)}))
    m = compute_metrics(res, bt_config())
    assert m["final_equity"] == pytest.approx(res.final_wallet) and m["n_trades"] == 1
    assert m["total_return"] == pytest.approx(res.final_wallet / 10_000.0 - 1)
    assert m["fees_total"] > 0 and m["slippage_total"] > 0 and m["exit_reasons"] == {"END_OF_PERIOD": 1}
    assert m["orders"] == {"FILLED": 1} and m["exposure_time"] == pytest.approx(5 / 6)
    assert 0 <= m["max_drawdown"] <= m["max_intrabar_drawdown"] + 1e-12
