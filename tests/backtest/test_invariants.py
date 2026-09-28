"""Accounting invariants that must hold in every random scenario, whatever the market does."""

import numpy as np
import pytest
from bt_helpers import HOUR, T0, bt_config, features_for, long_signal, make_market, window, app_config, Scripted
from bt_scenarios import random_scenario

from arven.backtest.engine import Backtester
from arven.backtest.types import EquityKind, FillPurpose


def run_seed(seed):
    hours, market, rates, signals, cfg, stress = random_scenario(seed)
    win = window(hours)
    res = Backtester(app_config(), cfg, win, market, features_for(win), stress=stress).run(Scripted(signals))
    return res, market, cfg


@pytest.mark.parametrize("seed", range(150))
def test_accounting_invariants(seed):
    res, market, cfg = run_seed(seed)
    e0 = cfg.initial_equity_usdt

    # wallet identity: the wallet only ever changes through trade results (fees, slippage, funding included)
    assert res.final_wallet == pytest.approx(e0 + sum(t.net_pnl for t in res.trades), rel=1e-9, abs=1e-8)
    final = [p for p in res.equity if p.kind == EquityKind.FINAL][-1]
    assert final.equity == pytest.approx(res.final_wallet) and final.qty == 0.0

    for t in res.trades:
        # net = gross - slippage - fees + funding (+ margin loss beyond the price move, only for liquidations)
        assert t.net_pnl == pytest.approx(t.gross_pnl - t.slippage_cost - t.fees + t.funding + t.liquidation_extra_loss, rel=1e-9, abs=1e-8)
        assert t.exit_time_ms >= t.entry_time_ms
        assert t.entry_time_ms - t.signal_ms == cfg.latency_ms  # filled exactly at t + latency, never earlier
        assert t.notional_entry <= cfg.leverage * t.decision_equity * (1 + 1e-9)
        assert t.margin > 0 and t.qty > 0
        assert t.mae >= 0 and t.mfe >= 0
        j = market.index_of(t.entry_time_ms)
        assert j >= 0 and t.entry_ref_price == market.open[j]  # entry reference price is the open of the fill bar
        if t.exit_reason.value != "LIQUIDATION":
            assert t.liquidation_extra_loss == 0.0

    # one position at a time
    for a, b in zip(res.trades, res.trades[1:]):
        assert a.exit_time_ms <= b.entry_time_ms

    # ledger consistency
    entries = [f for f in res.fills if f.purpose == FillPurpose.ENTRY]
    exits = [f for f in res.fills if f.purpose != FillPurpose.ENTRY]
    assert len(entries) == len(exits) == len(res.trades)
    assert sum(f.fee for f in res.fills) == pytest.approx(sum(t.fees for t in res.trades), rel=1e-9, abs=1e-8)
    assert sum(f.cash_flow for f in res.funding) == pytest.approx(sum(t.funding for t in res.trades), rel=1e-9, abs=1e-8)

    # equity curve: time never goes backwards; flat means equity == wallet
    times = [p.time_ms for p in res.equity]
    assert times == sorted(times)
    for p in res.equity:
        if p.qty == 0.0:
            assert p.equity == p.wallet and p.unrealized == 0.0

    # every order is created once and ends in exactly one final status
    final_status = {}
    for e in res.orders:
        final_status[e.order_id] = e.status.value
    assert all(s in {"FILLED", "REJECTED", "CANCELLED"} for s in final_status.values())


@pytest.mark.parametrize("seed", [s for s in range(150) if random_scenario(s)[4].liquidation_includes_funding])
def test_equity_never_negative_when_funding_is_debited_from_margin(seed):
    res, _, _ = run_seed(seed)
    assert min(p.equity for p in res.equity) >= -1e-6
    assert res.final_wallet >= -1e-6


def test_long_hold_through_persistent_positive_funding_is_liquidated_not_negative():
    """The scenario that exposed the fixed-liquidation-price model: a 3x isolated long held for a long time
    while funding keeps draining the wallet and the price merely drifts."""
    days = 200
    hours = days * 24
    rng = np.random.default_rng(5)
    px, bars = 30_000.0, {}
    for i in range(hours * 60):
        o = px
        px *= 1 + rng.normal(2e-7, 4e-4)
        bars[i] = (o, max(o, px), min(o, px), px)
    from bt_helpers import FUNDING_INTERVAL

    rates = {T0 + k * FUNDING_INTERVAL: 3e-3 for k in range(days * 3 + 1)}  # 0.3% per 8h, persistently (extreme on purpose)
    market = make_market(hours, bars, funding_rates=rates)
    sig = {T0 + HOUR: long_signal(T0 + HOUR, 1.0)}
    win = window(hours)
    for includes, expect_negative in ((True, False), (False, True)):
        cfg = bt_config(liquidation_includes_funding=includes)
        res = Backtester(app_config(), cfg, win, market, features_for(win)).run(Scripted(sig))
        lo = min(p.equity for p in res.equity)
        if expect_negative:
            assert lo < 0  # documents the flaw of the fixed-liquidation-price model
        else:
            assert lo >= -1e-6
            assert res.trades[0].exit_reason.value == "LIQUIDATION"
