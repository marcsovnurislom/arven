"""The fast engine must equal a naive bar-by-bar reference on hundreds of random scenarios.

The reference below is an independent, deliberately simple implementation of the specification in
``arven/backtest/execution.py`` (no skipping, plain floats, no shared accounting code). Any disagreement in
trades, exit reasons, funding, decision-time equity or final wallet fails the test.
"""

import numpy as np
import pytest
from bt_helpers import Scripted, app_config, features_for, window
from bt_scenarios import oracle, random_scenario

from arven.backtest.engine import Backtester

@pytest.mark.parametrize("seed", range(300))
def test_engine_equals_naive_reference(seed):
    hours, market, rates, signals, cfg, stress = random_scenario(seed)
    app = app_config()
    win = window(hours)
    res = Backtester(app, cfg, win, market, features_for(win), stress=stress).run(Scripted(signals))
    trades, funds, decisions, wallet = oracle(market, rates, signals, app, cfg, stress)

    assert len(res.trades) == len(trades), f"seed {seed}: trade count"
    for got, (te, tx, reason, q, net, pe, px) in zip(res.trades, trades):
        assert (got.entry_time_ms, got.exit_time_ms, got.exit_reason.value) == (te, tx, reason), f"seed {seed}"
        assert got.qty == pytest.approx(q, abs=1e-9)
        assert got.net_pnl == pytest.approx(net, rel=1e-9, abs=1e-9)
        assert got.entry_price == pytest.approx(pe, rel=1e-12) and got.exit_price == pytest.approx(px, rel=1e-12)
    assert len(res.funding) == len(funds)
    for f, (ft, cash) in zip(res.funding, funds):
        assert f.time_ms == ft and f.cash_flow == pytest.approx(cash, rel=1e-9, abs=1e-12)
    dec = [(p.time_ms, p.equity) for p in res.equity if p.kind.value == "DECISION"]
    assert [d[0] for d in dec] == [d[0] for d in decisions]
    np.testing.assert_allclose([d[1] for d in dec], [d[1] for d in decisions], rtol=1e-9, atol=1e-9)
    assert res.final_wallet == pytest.approx(wallet, rel=1e-9, abs=1e-9)


def test_random_scenarios_actually_exercise_every_exit_reason():
    seen = set()
    for seed in range(300):
        hours, market, rates, signals, cfg, stress = random_scenario(seed)
        win = window(hours)
        res = Backtester(app_config(), cfg, win, market, features_for(win), stress=stress).run(Scripted(signals))
        seen |= {t.exit_reason.value for t in res.trades}
    assert {"STOP", "TAKE_PROFIT", "TIME_STOP", "SIGNAL_CLOSE", "LIQUIDATION", "END_OF_PERIOD"} <= seen
