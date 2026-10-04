"""Risk engine: hand-computed cases for every rule, plus the stateful circuit breakers."""

import pytest

from arven.backtest.margin import liquidation_price
from arven.backtest.provider import PortfolioSnapshot
from arven.core.backtest_config import load_backtest_config
from arven.core.macro_config import MacroEvent
from arven.core.risk_config import load_risk_config
from arven.core.types import Action
from arven.decision.engine import ProposedDecision
from arven.regime.detector import Regime, TrendState, VolState
from arven.risk.engine import RiskEngine

CFG = load_risk_config()
BT = load_backtest_config()
HOUR = 3_600_000
DAY = 86_400_000
T0 = 10 * DAY  # a day boundary, well clear of t=0 edge cases

NORMAL = Regime(TrendState.UP, VolState.NORMAL, False, True)
HIGH = Regime(TrendState.UP, VolState.HIGH, False, True)
STRESS = Regime(TrendState.UP, VolState.NORMAL, True, True)


def flat(equity=10_000.0, side=0, order_pending=False):
    return PortfolioSnapshot(equity, equity, side, 0.0 if side == 0 else 0.1, 0.0, 0.0, equity, order_pending)


def proposal(action=Action.LONG, regime=NORMAL, stop_pct=0.02, tp_pct=0.04, score=0.6, contributing=("trend_momentum",), t_ms=T0, holding=60):
    return ProposedDecision(t_ms, action, score, 0.5, contributing, (), ("r",), regime, stop_pct, tp_pct, holding, ())


def engine():
    return RiskEngine(CFG, BT)


def test_no_trade_proposal_passes_through_with_no_signal():
    signal, rd = engine().apply(proposal(Action.NO_TRADE, stop_pct=None, tp_pct=None), flat(), T0, 1.0, 0.0)
    assert signal is None and rd.outcome == "no_proposal"


def test_normal_case_produces_a_signal_with_expected_sizing():
    signal, rd = engine().apply(proposal(stop_pct=0.02, tp_pct=0.04), flat(), T0, 1.0, 0.0)
    assert signal is not None and rd.outcome == "signal"
    assert signal.stop_pct == pytest.approx(0.02) and signal.take_profit_pct == pytest.approx(0.04)
    assert signal.notional_fraction == pytest.approx(CFG.risk_fraction_per_trade / 0.02)
    assert signal.action == Action.LONG and signal.t_ms == T0
    assert "trend_momentum" in signal.tag and "score=0.600" in signal.tag


# --- 1. data-quality gate -------------------------------------------------------------------------


@pytest.mark.parametrize("feat_ready", [0.0, float("nan"), 0.5])
def test_data_quality_gate_vetoes_when_not_ready(feat_ready):
    signal, rd = engine().apply(proposal(), flat(), T0, feat_ready, 0.0)
    assert signal is None and rd.outcome == "veto" and rd.reason == "stale_or_incomplete_data"


# --- 2. macro-event blackout (Stage 9a) ------------------------------------------------------------


def _event(t_ms=T0, event_type="FOMC", note=""):
    return MacroEvent(t_ms, event_type, note)


def test_no_events_configured_never_vetoes():
    signal, rd = RiskEngine(CFG, BT, macro_events=()).apply(proposal(), flat(), T0, 1.0, 0.0)
    assert signal is not None and rd.outcome == "signal"


def test_exactly_at_the_scheduled_time_vetoes():
    signal, rd = RiskEngine(CFG, BT, macro_events=(_event(T0),)).apply(proposal(), flat(), T0, 1.0, 0.0)
    assert signal is None and rd.outcome == "veto" and rd.reason == "macro_event_blackout"
    assert rd.detail["event_type"] == "FOMC" and rd.detail["scheduled_at_ms"] == T0


@pytest.mark.parametrize("delta", [-3600_000, -1, 0, 1, 3600_000])
def test_inside_the_symmetric_window_vetoes(delta):
    # CFG.macro_blackout_window_hours == 1.0 -> +/- 3_600_000 ms is exactly the boundary (inclusive)
    event_t = T0 + 3600_000
    signal, rd = RiskEngine(CFG, BT, macro_events=(_event(event_t),)).apply(proposal(t_ms=event_t + delta), flat(), event_t + delta, 1.0, 0.0)
    assert signal is None and rd.outcome == "veto" and rd.reason == "macro_event_blackout"


@pytest.mark.parametrize("delta", [-3600_001, 3600_001])
def test_just_outside_the_symmetric_window_does_not_veto(delta):
    event_t = T0 + 3600_000
    signal, rd = RiskEngine(CFG, BT, macro_events=(_event(event_t),)).apply(proposal(t_ms=event_t + delta), flat(), event_t + delta, 1.0, 0.0)
    assert signal is not None and rd.outcome == "signal"


def test_only_the_nearest_relevant_event_matters_among_several():
    events = (_event(T0 - 10 * HOUR, "CPI"), _event(T0, "FOMC"), _event(T0 + 10 * HOUR, "NFP"))
    signal, rd = RiskEngine(CFG, BT, macro_events=events).apply(proposal(), flat(), T0, 1.0, 0.0)
    assert signal is None and rd.detail["event_type"] == "FOMC"


def test_blackout_is_checked_before_the_portfolio_state_rules_but_a_vetoed_decision_still_updates_state():
    """Rule ordering: 1 (data quality) then 2 (blackout) then 7 (portfolio state) - a blackout veto must not
    bypass the stateful circuit-breaker bookkeeping (_update_state is called unconditionally at the top of
    apply, before any rule)."""
    eng = RiskEngine(CFG, BT, macro_events=(_event(T0),))
    signal, rd = eng.apply(proposal(), flat(equity=10_000.0), T0, 1.0, 0.0)
    assert signal is None and rd.reason == "macro_event_blackout"
    assert eng._peak_equity == 10_000.0  # state was still updated despite the veto


def test_blackout_does_not_apply_to_a_no_trade_proposal():
    signal, rd = RiskEngine(CFG, BT, macro_events=(_event(T0),)).apply(
        proposal(Action.NO_TRADE, stop_pct=None, tp_pct=None), flat(), T0, 1.0, 0.0
    )
    assert signal is None and rd.outcome == "no_proposal"  # never even reaches rule 1 or 2


# --- 7 (checked early): already-open position -----------------------------------------------------


def test_vetoes_when_a_position_is_already_open():
    signal, rd = engine().apply(proposal(), flat(side=1), T0, 1.0, 0.0)
    assert signal is None and rd.reason == "position_already_open"


def test_vetoes_when_an_order_is_already_pending():
    signal, rd = engine().apply(proposal(), flat(order_pending=True), T0, 1.0, 0.0)
    assert signal is None and rd.reason == "position_already_open"


# --- 3. volatility guard ---------------------------------------------------------------------------


def test_stress_vetoes_when_veto_on_stress_is_true():
    signal, rd = engine().apply(proposal(regime=STRESS), flat(), T0, 1.0, 0.0)
    assert signal is None and rd.reason == "extreme_volatility_stress"


def test_stress_does_not_veto_when_veto_on_stress_is_false():
    cfg2 = CFG.model_copy(update={"veto_on_stress": False})
    signal, rd = RiskEngine(cfg2, BT).apply(proposal(regime=STRESS), flat(), T0, 1.0, 0.0)
    assert signal is not None


def test_high_vol_reduces_notional_fraction():
    e = engine()
    normal_signal, _ = e.apply(proposal(regime=NORMAL, stop_pct=0.02), flat(), T0, 1.0, 0.0)
    e2 = engine()
    high_signal, _ = e2.apply(proposal(regime=HIGH, stop_pct=0.02), flat(), T0, 1.0, 0.0)
    assert high_signal.notional_fraction == pytest.approx(normal_signal.notional_fraction * CFG.high_vol_size_multiplier)


# --- 4. funding guard -------------------------------------------------------------------------------


def test_extreme_funding_on_the_paying_side_vetoes():
    signal, rd = engine().apply(proposal(action=Action.LONG), flat(), T0, 1.0, CFG.funding_guard_veto_z)
    assert signal is None and rd.reason == "extreme_funding"


def test_funding_guard_reduces_below_veto_threshold():
    e = engine()
    base, _ = e.apply(proposal(stop_pct=0.02), flat(), T0, 1.0, 0.0)
    e2 = engine()
    z = (CFG.funding_guard_reduce_z + CFG.funding_guard_veto_z) / 2
    reduced, _ = e2.apply(proposal(stop_pct=0.02), flat(), T0, 1.0, z)
    assert reduced.notional_fraction == pytest.approx(base.notional_fraction * CFG.funding_guard_reduce_multiplier)


def test_funding_guard_only_fires_on_the_paying_side_not_the_receiving_side():
    # LONG pays when fund_z is very positive; a very NEGATIVE fund_z means longs receive -> no guard.
    signal, rd = engine().apply(proposal(action=Action.LONG), flat(), T0, 1.0, -CFG.funding_guard_veto_z)
    assert signal is not None and rd.outcome == "signal"


def test_funding_guard_sign_is_mirrored_for_shorts():
    signal, rd = engine().apply(proposal(action=Action.SHORT, contributing=("mean_reversion",)), flat(), T0, 1.0, -CFG.funding_guard_veto_z)
    assert signal is None and rd.reason == "extreme_funding"
    signal2, _ = engine().apply(proposal(action=Action.SHORT, contributing=("mean_reversion",)), flat(), T0, 1.0, CFG.funding_guard_veto_z)
    assert signal2 is not None  # shorts don't pay when the rate is very positive


def test_nan_funding_z_is_treated_as_no_guard():
    signal, rd = engine().apply(proposal(), flat(), T0, 1.0, float("nan"))
    assert signal is not None and rd.outcome == "signal"


# --- 5. stop & target bounds -----------------------------------------------------------------------


def test_stop_below_minimum_is_clamped_up():
    signal, rd = engine().apply(proposal(stop_pct=CFG.min_stop_pct / 2, tp_pct=CFG.min_stop_pct), flat(), T0, 1.0, 0.0)
    assert signal.stop_pct == pytest.approx(CFG.min_stop_pct)


def test_stop_above_maximum_is_clamped_down():
    signal, rd = engine().apply(proposal(stop_pct=CFG.max_stop_pct * 2, tp_pct=CFG.max_stop_pct * 3), flat(), T0, 1.0, 0.0)
    assert signal.stop_pct == pytest.approx(CFG.max_stop_pct)


def test_target_extended_to_meet_minimum_reward_risk_ratio():
    stop = 0.02
    signal, rd = engine().apply(proposal(stop_pct=stop, tp_pct=stop * 0.5), flat(), T0, 1.0, 0.0)  # tp far too tight
    assert signal.take_profit_pct == pytest.approx(stop * CFG.min_reward_risk_ratio)


def test_target_already_meeting_the_ratio_is_left_alone():
    stop, tp = 0.02, 0.10
    signal, rd = engine().apply(proposal(stop_pct=stop, tp_pct=tp), flat(), T0, 1.0, 0.0)
    assert signal.take_profit_pct == pytest.approx(tp)


# --- 6. position sizing -----------------------------------------------------------------------------


def test_sizing_formula_matches_risk_fraction_over_stop_distance():
    stop = 0.015
    signal, _ = engine().apply(proposal(stop_pct=stop, tp_pct=stop * 2), flat(), T0, 1.0, 0.0)
    assert signal.notional_fraction == pytest.approx(CFG.risk_fraction_per_trade / stop)


def test_sizing_is_capped_at_max_notional_fraction():
    tiny_stop = CFG.min_stop_pct  # would otherwise imply a huge fraction
    cfg2 = CFG.model_copy(update={"risk_fraction_per_trade": 0.5})
    signal, _ = RiskEngine(cfg2, BT).apply(proposal(stop_pct=tiny_stop, tp_pct=tiny_stop * 2), flat(), T0, 1.0, 0.0)
    assert signal.notional_fraction == pytest.approx(min(CFG.max_notional_fraction, BT.leverage))


def test_sizing_is_capped_at_leverage():
    cfg2 = CFG.model_copy(update={"risk_fraction_per_trade": 0.5, "max_notional_fraction": 100.0})
    signal, _ = RiskEngine(cfg2, BT).apply(proposal(stop_pct=CFG.min_stop_pct, tp_pct=CFG.min_stop_pct * 2), flat(), T0, 1.0, 0.0)
    assert signal.notional_fraction == pytest.approx(BT.leverage)


# --- 8. liquidation-distance check -----------------------------------------------------------------


def test_liquidation_distance_formula_matches_margin_module():
    # At the repo's default leverage (3x) the liquidation distance (~33%) is far beyond max_stop_pct (8%), so
    # the veto path needs a much higher leverage to be reachable through a realistic stop_pct. Use a relaxed
    # max_stop_pct too, so the clamp in step 5 doesn't itself hide the boundary being tested here.
    bt_hi_lev = BT.model_copy(update={"leverage": 20.0, "maintenance_margin_rate": 0.004})
    cfg_wide = CFG.model_copy(update={"max_stop_pct": 0.5})
    e = RiskEngine(cfg_wide, bt_hi_lev)
    expected = abs(1.0 - liquidation_price(1, 1.0, bt_hi_lev.leverage, bt_hi_lev.maintenance_margin_rate))
    assert expected < cfg_wide.max_stop_pct  # otherwise this scenario doesn't exercise the veto at all
    ok_stop = expected / cfg_wide.liquidation_min_multiple * 0.5
    bad_stop = expected / cfg_wide.liquidation_min_multiple * 1.5
    ok, _ = e.apply(proposal(stop_pct=ok_stop, tp_pct=ok_stop * 2), flat(), T0, 1.0, 0.0)
    assert ok is not None
    bad, rd = RiskEngine(cfg_wide, bt_hi_lev).apply(proposal(stop_pct=bad_stop, tp_pct=bad_stop * 2), flat(), T0, 1.0, 0.0)
    assert bad is None and rd.reason == "stop_too_close_to_liquidation"


def test_liquidation_distance_is_independent_of_direction_for_symmetric_config():
    e1, e2 = engine(), engine()
    long_sig, _ = e1.apply(proposal(action=Action.LONG, stop_pct=CFG.max_stop_pct, tp_pct=CFG.max_stop_pct * 2), flat(), T0, 1.0, 0.0)
    short_sig, _ = e2.apply(proposal(action=Action.SHORT, stop_pct=CFG.max_stop_pct, tp_pct=CFG.max_stop_pct * 2, contributing=("mean_reversion",)), flat(), T0, 1.0, 0.0)
    assert (long_sig is None) == (short_sig is None)


# --- stateful circuit breakers ----------------------------------------------------------------------


def test_drawdown_halt_trips_and_resumes():
    """The decline is spread over several UTC days, each move well under max_daily_loss_pct, so only the
    running-peak drawdown check (not the daily-loss check) can be responsible for the veto."""
    e = engine()
    per_day_loss = CFG.max_daily_loss_pct / 4
    equity, t = 10_000.0, T0
    e.apply(proposal(t_ms=t), flat(equity=equity), t, 1.0, 0.0)  # sets peak = 10 000
    while (10_000.0 - equity) / 10_000.0 < CFG.max_drawdown_halt_pct:
        equity *= 1 - per_day_loss
        t += DAY
        signal, rd = e.apply(proposal(t_ms=t), flat(equity=equity), t, 1.0, 0.0)
    assert signal is None and rd.reason == "max_drawdown_halt"

    still_down = 10_000.0 * (1 - (CFG.max_drawdown_halt_pct + CFG.drawdown_resume_pct) / 2)
    t += DAY
    signal2, rd2 = e.apply(proposal(t_ms=t), flat(equity=still_down), t, 1.0, 0.0)
    assert signal2 is None and rd2.reason == "max_drawdown_halt"  # still halted: hasn't recovered enough

    resume_equity = 10_000.0 * (1 - CFG.drawdown_resume_pct + 0.001)
    t += DAY
    signal3, rd3 = e.apply(proposal(t_ms=t), flat(equity=resume_equity), t, 1.0, 0.0)
    assert signal3 is not None


def test_daily_loss_halt_trips_and_resets_at_the_next_utc_day():
    e = engine()
    e.apply(proposal(), flat(equity=10_000.0), T0, 1.0, 0.0)  # sets day_start_equity
    loss_equity = 10_000.0 * (1 - CFG.max_daily_loss_pct)
    signal, rd = e.apply(proposal(t_ms=T0 + HOUR), flat(equity=loss_equity), T0 + HOUR, 1.0, 0.0)
    assert signal is None and rd.reason == "max_daily_loss_halt"
    next_day = T0 + DAY
    signal2, rd2 = e.apply(proposal(t_ms=next_day), flat(equity=loss_equity), next_day, 1.0, 0.0)
    assert signal2 is not None  # a new UTC day resets the halt (and the day_start baseline)


def _entry_hold_close(e, equity, t, factor):
    """One full cycle: decide to enter while flat, one decision while the position is open (registers the
    side transition), then a close with equity multiplied by ``factor`` (< 1 = loss, > 1 = win)."""
    e.apply(proposal(t_ms=t), flat(equity=equity, side=0), t, 1.0, 0.0)
    t += HOUR
    e.apply(proposal(action=Action.NO_TRADE, stop_pct=None, tp_pct=None, t_ms=t), flat(equity=equity, side=1), t, 1.0, 0.0)
    equity *= factor
    t += HOUR
    e.apply(proposal(action=Action.NO_TRADE, stop_pct=None, tp_pct=None, t_ms=t), flat(equity=equity, side=0), t, 1.0, 0.0)
    return equity, t + DAY  # advance a full day so the daily-loss baseline resets before the next cycle


def test_cooldown_after_consecutive_losses():
    """Each cycle happens on its own UTC day (so the daily-loss halt never masks the cooldown being tested)
    and loses only a small, fixed fraction (so cumulative drawdown stays far under the drawdown halt)."""
    e = engine()
    equity, t = 10_000.0, T0
    for _ in range(CFG.cooldown_after_losses):
        equity, t = _entry_hold_close(e, equity, t, 0.999)
    signal, rd = e.apply(proposal(t_ms=t), flat(equity=equity, side=0), t, 1.0, 0.0)
    assert signal is None and rd.reason == "loss_streak_cooldown"
    for _ in range(CFG.cooldown_bars):
        t += HOUR
        e.apply(proposal(action=Action.NO_TRADE, stop_pct=None, tp_pct=None, t_ms=t), flat(equity=equity), t, 1.0, 0.0)
    signal2, rd2 = e.apply(proposal(t_ms=t + HOUR), flat(equity=equity), t + HOUR, 1.0, 0.0)
    assert signal2 is not None  # cooldown has expired


def test_a_winning_trade_resets_the_loss_streak():
    e = engine()
    equity, t = 10_000.0, T0
    for _ in range(CFG.cooldown_after_losses - 1):
        equity, t = _entry_hold_close(e, equity, t, 0.999)
    equity, t = _entry_hold_close(e, equity, t, 1.001)  # one more close, but a WIN this time
    signal, rd = e.apply(proposal(t_ms=t), flat(equity=equity, side=0), t, 1.0, 0.0)
    assert signal is not None  # the streak was broken by the win: no cooldown


def test_reset_clears_all_circuit_breaker_state():
    e = engine()
    e.apply(proposal(), flat(equity=10_000.0), T0, 1.0, 0.0)
    dd_equity = 10_000.0 * (1 - CFG.max_drawdown_halt_pct)
    e.apply(proposal(t_ms=T0 + HOUR), flat(equity=dd_equity), T0 + HOUR, 1.0, 0.0)
    e.reset()
    signal, rd = e.apply(proposal(t_ms=T0), flat(equity=dd_equity), T0, 1.0, 0.0)
    assert signal is not None  # halt state, peak equity and day tracking are all gone after reset


def test_apply_rejects_out_of_order_or_repeated_time():
    e = engine()
    e.apply(proposal(t_ms=T0), flat(), T0, 1.0, 0.0)
    with pytest.raises(ValueError):
        e.apply(proposal(t_ms=T0), flat(), T0, 1.0, 0.0)
    with pytest.raises(ValueError):
        e.apply(proposal(t_ms=T0 - HOUR), flat(), T0 - HOUR, 1.0, 0.0)
