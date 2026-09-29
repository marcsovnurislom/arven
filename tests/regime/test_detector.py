"""Regime classification: hand-computed cases, hysteresis, and sequential-only use."""

import numpy as np
import pytest
from stage5_helpers import T0, constant_rows, single_row, view_rows

from arven.backtest.clock import HOUR_MS
from arven.core.regime_config import load_regime_config
from arven.regime.detector import (
    Regime,
    RegimeDetector,
    TrendState,
    VolState,
    classify_series,
    raw_stress,
    raw_trend,
    volatility_percentile,
)

CFG = load_regime_config()


def row(**over):
    base = {"h4_adx": 10.0, "h1_adx": 10.0, "h4_ema_slope": 0.0, "h4_ema_dist_200": 0.0, "fund_z": 0.0, "oi_chg_1h": 0.0}
    base.update(over)
    return base


# --- trend --------------------------------------------------------------------------------------


def test_raw_trend_up_and_down_hand_cases():
    up = row(h4_adx=25.0, h1_adx=20.0, h4_ema_slope=0.01, h4_ema_dist_200=0.02)
    assert raw_trend(up, CFG) == TrendState.UP
    down = row(h4_adx=25.0, h1_adx=20.0, h4_ema_slope=-0.01, h4_ema_dist_200=-0.02)
    assert raw_trend(down, CFG) == TrendState.DOWN


def test_raw_trend_none_when_adx_below_threshold_or_confirmation_fails():
    weak4h = row(h4_adx=15.0, h1_adx=20.0, h4_ema_slope=0.01, h4_ema_dist_200=0.02)
    assert raw_trend(weak4h, CFG) == TrendState.NONE
    weak1h = row(h4_adx=25.0, h1_adx=5.0, h4_ema_slope=0.01, h4_ema_dist_200=0.02)
    assert raw_trend(weak1h, CFG) == TrendState.NONE  # 4h trending but 1h doesn't confirm


def test_raw_trend_none_when_slope_and_price_disagree():
    disagree = row(h4_adx=30.0, h1_adx=30.0, h4_ema_slope=0.01, h4_ema_dist_200=-0.01)
    assert raw_trend(disagree, CFG) == TrendState.NONE
    zero_slope = row(h4_adx=30.0, h1_adx=30.0, h4_ema_slope=0.0, h4_ema_dist_200=0.01)
    assert raw_trend(zero_slope, CFG) == TrendState.NONE


def test_raw_trend_missing_data_is_none_not_a_crash():
    assert raw_trend(row(h4_adx=float("nan")), CFG) == TrendState.NONE


# --- volatility -----------------------------------------------------------------------------------


def test_volatility_percentile_hand_case():
    hist = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    pct, n = volatility_percentile(hist)
    assert pct == 80.0 and n == 5  # 4 of 5 values are strictly below 5.0


def test_volatility_percentile_ignores_nan_and_handles_all_nan():
    hist = np.array([np.nan, 1.0, 2.0, 3.0])
    pct, n = volatility_percentile(hist)
    assert n == 3 and pct == pytest.approx(200 / 3)
    pct2, n2 = volatility_percentile(np.array([np.nan, np.nan]))
    assert n2 == 0 and pct2 == 50.0  # NaN "now": neutral, not-confident


def test_vol_states_hand_thresholds():
    from arven.regime.detector import raw_vol

    n = CFG.volatility.min_history_bars
    hist = list(range(1, n + 1))  # "now" is the maximum -> top percentile, and exactly meets min_history_bars
    view, t = view_rows([{"h1_atr_pct": float(x)} for x in hist])
    state, confident = raw_vol(view, t, CFG)
    assert state == VolState.HIGH and confident
    view2, t2 = view_rows([{"h1_atr_pct": 1.0} for _ in range(n)])
    state2, _ = raw_vol(view2, t2, CFG)
    assert state2 == VolState.LOW  # constant series: "now" ties everything -> percentile 0


def test_vol_not_confident_below_min_history():
    view, t = constant_rows(CFG.volatility.min_history_bars - 1, {"h1_atr_pct": 0.01})
    from arven.regime.detector import raw_vol

    _, confident = raw_vol(view, t, CFG)
    assert not confident


# --- stress ---------------------------------------------------------------------------------------


def test_raw_stress_hand_cases():
    assert raw_stress(row(fund_z=4.0), CFG) is True
    assert raw_stress(row(oi_chg_1h=0.1), CFG) is True
    assert raw_stress(row(fund_z=-4.0), CFG) is True  # magnitude, either sign
    assert raw_stress(row(), CFG) is False
    assert raw_stress(row(fund_z=float("nan"), oi_chg_1h=float("nan")), CFG) is False


# --- Regime / label ---------------------------------------------------------------------------------


def test_regime_label_formatting():
    r = Regime(TrendState.UP, VolState.NORMAL, False, True)
    assert r.label == "TREND_UP/NORMAL"
    r2 = Regime(TrendState.NONE, VolState.HIGH, True, True)
    assert r2.label == "NO_TREND/HIGH+STRESS"


# --- stateful detector: hysteresis / dwell -----------------------------------------------------


def strong_up():
    return {"h4_adx": 30.0, "h1_adx": 30.0, "h4_ema_slope": 0.01, "h4_ema_dist_200": 0.02, "h1_atr_pct": 0.01}


def strong_down():
    return {"h4_adx": 30.0, "h1_adx": 30.0, "h4_ema_slope": -0.01, "h4_ema_dist_200": -0.02, "h1_atr_pct": 0.01}


def test_detector_needs_dwell_to_enter_a_trend_from_the_initial_state():
    """Hysteresis applies uniformly, including the very first transition away from NO_TREND: this avoids
    special-casing "first ever" vs. "later" switches, and is what stops a single noisy bar from starting a
    trend the moment the run begins."""
    n = CFG.min_dwell_bars
    view, _ = view_rows([strong_up()] * n)
    det = RegimeDetector(CFG)
    labels = [det.step(view, T0 + i * HOUR_MS).trend for i in range(n)]
    assert labels[:-1] == [TrendState.NONE] * (n - 1)
    assert labels[-1] == TrendState.UP


def test_detector_requires_min_dwell_bars_before_switching():
    n_prime = CFG.min_dwell_bars  # establish TREND_UP first
    n_switch = CFG.min_dwell_bars + 3
    rows = [strong_up()] * n_prime + [strong_down()] * n_switch
    view, _ = view_rows(rows)
    det = RegimeDetector(CFG)
    labels = [det.step(view, T0 + i * HOUR_MS).trend for i in range(len(rows))]
    assert labels[n_prime - 1] == TrendState.UP
    switch_index = n_prime + CFG.min_dwell_bars - 1
    assert labels[n_prime:switch_index] == [TrendState.UP] * (CFG.min_dwell_bars - 1)
    assert all(s == TrendState.DOWN for s in labels[switch_index:])


def test_detector_candidate_resets_if_it_reverts_before_dwell_completes():
    n_prime = CFG.min_dwell_bars
    rows = [strong_up()] * n_prime + [strong_down()] * (CFG.min_dwell_bars - 1) + [strong_up()] * 2
    view, _ = view_rows(rows)
    det = RegimeDetector(CFG)
    out = [det.step(view, T0 + i * HOUR_MS).trend for i in range(len(rows))]
    assert all(s == TrendState.UP for s in out[n_prime - 1 :])  # DOWN never completed dwell before reverting


def test_detector_reset_clears_state():
    det = RegimeDetector(CFG)
    view, _ = view_rows([strong_up()] * CFG.min_dwell_bars)
    for i in range(CFG.min_dwell_bars):
        det.step(view, T0 + i * HOUR_MS)
    assert det._current_trend == TrendState.UP
    det.reset()
    assert det._current_trend == TrendState.NONE
    assert det.step(view, T0) is not None  # can be reused from t=T0 again after reset


def test_detector_rejects_out_of_order_or_repeated_time():
    det = RegimeDetector(CFG)
    view, t = single_row(strong_up())
    det.step(view, t)
    with pytest.raises(ValueError):
        det.step(view, t)  # same time again
    with pytest.raises(ValueError):
        det.step(view, t - HOUR_MS)  # earlier time


def test_classify_series_matches_manual_stepping():
    n = 10
    rows = [strong_up() if i % 2 == 0 else strong_down() for i in range(n)]
    view, _ = view_rows(rows)
    grid = np.array([T0 + i * HOUR_MS for i in range(n)], dtype=np.int64)
    batch = classify_series(view, grid, CFG)
    manual_det = RegimeDetector(CFG)
    manual = [manual_det.step(view, int(t)) for t in grid]
    assert batch == manual
