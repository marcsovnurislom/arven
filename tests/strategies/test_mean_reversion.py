"""Mean-reversion strategy: hand-computed cases."""

import pytest
from stage5_helpers import single_row

from arven.core.strategies_config import load_strategies_config
from arven.strategies.mean_reversion import MeanReversionStrategy

CFG = load_strategies_config().mean_reversion
S = MeanReversionStrategy(CFG)


def row(**over):
    base = dict(h1_bb_z=0.0, h1_rsi=50.0, h1_atr_pct=0.02)
    base.update(over)
    return base


def test_oversold_extreme_gives_a_long_candidate():
    view, t = single_row(row(h1_bb_z=-CFG.bb_z_threshold - 0.5, h1_rsi=CFG.rsi_oversold_confirm - 1))
    c = S.evaluate(view, t)
    assert c is not None and c.direction == 1 and c.strategy_id == "mean_reversion"
    assert c.stop_pct == pytest.approx(CFG.stop_atr_mult * 0.02)
    assert c.take_profit_pct == pytest.approx(CFG.take_profit_atr_mult * 0.02)


def test_overbought_extreme_gives_a_short_candidate():
    view, t = single_row(row(h1_bb_z=CFG.bb_z_threshold + 0.5, h1_rsi=CFG.rsi_overbought_confirm + 1))
    c = S.evaluate(view, t)
    assert c is not None and c.direction == -1


def test_z_extreme_without_rsi_confirmation_gives_no_signal():
    view, t = single_row(row(h1_bb_z=-CFG.bb_z_threshold - 1, h1_rsi=50.0))
    assert S.evaluate(view, t) is None


def test_rsi_extreme_without_z_confirmation_gives_no_signal():
    view, t = single_row(row(h1_bb_z=0.0, h1_rsi=CFG.rsi_oversold_confirm - 1))
    assert S.evaluate(view, t) is None


def test_boundary_is_inclusive():
    view, t = single_row(row(h1_bb_z=-CFG.bb_z_threshold, h1_rsi=CFG.rsi_oversold_confirm))
    assert S.evaluate(view, t) is not None
    view2, t2 = single_row(row(h1_bb_z=-CFG.bb_z_threshold + 0.001, h1_rsi=CFG.rsi_oversold_confirm))
    assert S.evaluate(view2, t2) is None


def test_strength_scales_with_z_and_is_clamped():
    view, t = single_row(row(h1_bb_z=-CFG.bb_z_strength_scale / 2, h1_rsi=CFG.rsi_oversold_confirm))
    c = S.evaluate(view, t)
    assert c.strength == pytest.approx(0.5)
    view2, t2 = single_row(row(h1_bb_z=-CFG.bb_z_strength_scale * 10, h1_rsi=CFG.rsi_oversold_confirm))
    assert S.evaluate(view2, t2).strength == 1.0


@pytest.mark.parametrize("missing", ["h1_bb_z", "h1_rsi", "h1_atr_pct"])
def test_missing_feature_gives_no_signal(missing):
    r = row(h1_bb_z=-3.0, h1_rsi=20.0)
    r.pop(missing)
    view, t = single_row(r)
    assert S.evaluate(view, t) is None
