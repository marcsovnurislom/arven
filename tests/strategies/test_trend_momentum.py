"""Trend/Momentum strategy: hand-computed cases."""

import pytest
from stage5_helpers import single_row

from arven.core.strategies_config import load_strategies_config
from arven.strategies.trend_momentum import TrendMomentumStrategy

CFG = load_strategies_config().trend_momentum
S = TrendMomentumStrategy(CFG)


def bull_row(**over):
    # dist_fast - dist_slow < 0 (fast EMA above slow EMA) => bullish cross
    base = dict(
        h1_ema_dist_20=0.01, h1_ema_dist_50=0.02,  # 0.01 - 0.02 = -0.01 < 0
        h4_adx=25.0, h4_ema_slope=0.005,
        h1_macd_hist=0.001, h1_rsi=55.0, h1_atr_pct=0.02,
    )
    base.update(over)
    return base


def bear_row(**over):
    base = dict(
        h1_ema_dist_20=0.02, h1_ema_dist_50=0.01,  # 0.02 - 0.01 = 0.01 > 0 -> bearish
        h4_adx=25.0, h4_ema_slope=-0.005,
        h1_macd_hist=-0.001, h1_rsi=45.0, h1_atr_pct=0.02,
    )
    base.update(over)
    return base


def test_bullish_cross_with_confirmation_gives_a_long_candidate():
    view, t = single_row(bull_row())
    c = S.evaluate(view, t)
    assert c is not None and c.direction == 1 and c.strategy_id == "trend_momentum"
    assert c.stop_pct == pytest.approx(CFG.stop_atr_mult * 0.02)
    assert c.take_profit_pct == pytest.approx(CFG.take_profit_atr_mult * 0.02)
    assert c.max_holding_minutes == CFG.max_holding_minutes
    assert 0 < c.strength <= 1.0
    assert len(c.reasons) > 0


def test_bearish_cross_gives_a_short_candidate():
    view, t = single_row(bear_row())
    c = S.evaluate(view, t)
    assert c is not None and c.direction == -1


def test_exact_ema_tie_gives_no_signal():
    view, t = single_row(bull_row(h1_ema_dist_20=0.015, h1_ema_dist_50=0.015))
    assert S.evaluate(view, t) is None


def test_weak_adx_blocks_the_signal():
    view, t = single_row(bull_row(h4_adx=CFG.adx_4h_threshold - 0.01))
    assert S.evaluate(view, t) is None


def test_slope_disagreeing_with_cross_direction_blocks():
    view, t = single_row(bull_row(h4_ema_slope=-0.005))  # bullish cross but 4h slope down
    assert S.evaluate(view, t) is None


def test_macd_disagreement_blocks_when_confirmation_required():
    view, t = single_row(bull_row(h1_macd_hist=-0.001))
    assert S.evaluate(view, t) is None
    cfg2 = CFG.model_copy(update={"require_macd_confirm": False})
    assert TrendMomentumStrategy(cfg2).evaluate(view, t) is not None


def test_rsi_block_on_each_side():
    view, t = single_row(bull_row(h1_rsi=CFG.rsi_overbought_block))
    assert S.evaluate(view, t) is None  # long blocked: already overbought
    view2, t2 = single_row(bear_row(h1_rsi=CFG.rsi_oversold_block))
    assert S.evaluate(view2, t2) is None  # short blocked: already oversold


def test_strength_scales_with_adx_and_is_clamped_to_one():
    view, t = single_row(bull_row(h4_adx=CFG.adx_strength_scale / 2))
    c = S.evaluate(view, t)
    assert c.strength == pytest.approx(0.5)
    view2, t2 = single_row(bull_row(h4_adx=CFG.adx_strength_scale * 10))
    c2 = S.evaluate(view2, t2)
    assert c2.strength == 1.0


@pytest.mark.parametrize("missing", ["h1_ema_dist_20", "h4_adx", "h4_ema_slope", "h1_macd_hist", "h1_rsi", "h1_atr_pct"])
def test_missing_any_required_feature_gives_no_signal(missing):
    row = bull_row()
    row.pop(missing)
    view, t = single_row(row)
    assert S.evaluate(view, t) is None


def test_configurable_ema_periods_are_read_correctly():
    cfg2 = CFG.model_copy(update={"ema_fast": 20, "ema_slow": 200})
    row = dict(bull_row())
    row["h1_ema_dist_200"] = 0.05  # slow = 200, dist_fast(0.01) - dist_slow(0.05) < 0 -> bullish
    view, t = single_row(row)
    c = TrendMomentumStrategy(cfg2).evaluate(view, t)
    assert c is not None and c.direction == 1
