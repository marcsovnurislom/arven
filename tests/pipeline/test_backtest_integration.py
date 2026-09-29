"""Accounting/execution integration: Stage 4's own invariants (unchanged) must hold when the signals come
from the real Stage 5 pipeline instead of a scripted or baseline provider - proof that Stage 5 talks to
Stage 4 only through the ``SignalProvider``/``Signal`` contract, never around it."""

import numpy as np
import pytest
from bt_helpers import app_config, bt_config, window
from pipeline_helpers import make_feature_data, make_pipeline, random_1m_market

from arven.backtest.engine import Backtester
from arven.backtest.types import EquityKind, FillPurpose

SEEDS = list(range(30))


def run(seed, days=180, stress=False):
    feats = make_feature_data(days, seed)
    market = random_1m_market(days * 24, seed=seed + 1000)
    win = window(days * 24)
    return Backtester(app_config(), bt_config(), win, market, feats, stress=stress).run(make_pipeline())


@pytest.mark.parametrize("seed", SEEDS)
def test_accounting_invariants_hold_when_driven_by_the_stage5_pipeline(seed):
    res = run(seed, stress=seed % 5 == 0)
    e0 = bt_config().initial_equity_usdt

    assert res.final_wallet == pytest.approx(e0 + sum(t.net_pnl for t in res.trades), rel=1e-9, abs=1e-8)
    final = [p for p in res.equity if p.kind == EquityKind.FINAL][-1]
    assert final.equity == pytest.approx(res.final_wallet) and final.qty == 0.0

    for t in res.trades:
        assert t.net_pnl == pytest.approx(t.gross_pnl - t.slippage_cost - t.fees + t.funding + t.liquidation_extra_loss, rel=1e-9, abs=1e-8)
        assert t.exit_time_ms >= t.entry_time_ms
        assert t.notional_entry <= bt_config().leverage * t.decision_equity * (1 + 1e-9)
        assert t.margin > 0 and t.qty > 0
        # every Stage 5 signal carries the contributing strategies and regime in its tag
        assert "|" in t.tag and any(s in t.tag for s in ("trend_momentum", "breakout", "mean_reversion"))

    for a, b in zip(res.trades, res.trades[1:]):
        assert a.exit_time_ms <= b.entry_time_ms  # one position at a time

    entries = [f for f in res.fills if f.purpose == FillPurpose.ENTRY]
    exits = [f for f in res.fills if f.purpose != FillPurpose.ENTRY]
    assert len(entries) == len(exits) == len(res.trades)

    times = [p.time_ms for p in res.equity]
    assert times == sorted(times)
    for p in res.equity:
        if p.qty == 0.0:
            assert p.equity == p.wallet and p.unrealized == 0.0


def test_no_liquidation_beyond_a_sane_ceiling():
    """The risk engine's own liquidation-distance rule should make liquidations rare at the default config
    (leverage 3x, ~33% distance vs a stop capped at 8%); if a run does liquidate, that must come from a real
    extreme intrabar move, not a mis-sized position. Not a hard causal guarantee (extreme synthetic wicks can
    still liquidate) - just a sanity ceiling."""
    liquidations = total = 0
    for seed in SEEDS:
        res = run(seed)
        total += len(res.trades)
        liquidations += sum(1 for t in res.trades if t.exit_reason.value == "LIQUIDATION")
    assert total > 0
    assert liquidations / total < 0.5


def test_signal_notional_fraction_never_exceeds_the_configured_leverage():
    for seed in SEEDS[:15]:
        res = run(seed)
        for t in res.trades:
            assert t.notional_entry / t.decision_equity <= bt_config().leverage * (1 + 1e-9)


def test_liquidation_extra_loss_is_zero_for_every_non_liquidation_exit():
    for seed in SEEDS[:15]:
        res = run(seed)
        for t in res.trades:
            if t.exit_reason.value != "LIQUIDATION":
                assert t.liquidation_extra_loss == 0.0


def test_stop_exits_have_a_negative_r_multiple_near_minus_one():
    """r_multiple = net_pnl / (qty * |entry - stop|); a stop-loss exit should land close to -1 (net of the
    entry/exit costs baked into net_pnl), never a large positive number."""
    for seed in SEEDS[:15]:
        res = run(seed)
        for t in res.trades:
            if t.exit_reason.value == "STOP" and not np.isnan(t.r_multiple):
                assert -2.0 < t.r_multiple < 0.2


def test_take_profit_exits_have_a_positive_r_multiple_at_least_the_configured_minimum():
    """A take-profit exit's r_multiple should be roughly >= min_reward_risk_ratio (risk.yaml), net of costs
    eating a bit of the edge; use a generous tolerance since costs and the weighted-average hint both shift it."""
    from arven.core.risk_config import load_risk_config

    min_rr = load_risk_config().min_reward_risk_ratio
    seen = 0
    for seed in SEEDS[:15]:
        res = run(seed)
        for t in res.trades:
            if t.exit_reason.value == "TAKE_PROFIT" and not np.isnan(t.r_multiple):
                seen += 1
                assert t.r_multiple > min_rr * 0.5  # generous: costs and rounding shave some of the edge off
    assert seen > 0
