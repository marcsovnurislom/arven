"""Breakout strategy: compression-then-expansion, hand-computed cases."""

import pytest
from stage5_helpers import view_rows

from arven.core.strategies_config import load_strategies_config
from arven.strategies.breakout import BreakoutStrategy

CFG = load_strategies_config().breakout
S = BreakoutStrategy(CFG)
N = CFG.bb_width_window_bars


def make_window(widths, donchian, atr_pct=0.02):
    """``widths`` fills the whole window (last value is "now"); donchian/atr apply to the last row only."""
    assert len(widths) == N
    rows = [{"h1_bb_width": w} for w in widths]
    rows[-1]["h1_donchian_pos_24"] = donchian
    rows[-1]["h1_atr_pct"] = atr_pct
    return view_rows(rows)


def flat_with_squeeze(base=0.05, squeeze=0.01, squeeze_at=None):
    widths = [base] * N
    if squeeze_at is not None:
        widths[squeeze_at] = squeeze
    return widths


def test_breakout_long_after_a_recent_squeeze():
    at = N - 1 - CFG.compression_lookback_bars // 2  # inside the lookback window, before "now"
    widths = flat_with_squeeze(squeeze_at=at)
    view, t = make_window(widths, donchian=1.0)
    c = S.evaluate(view, t)
    assert c is not None and c.direction == 1 and c.strategy_id == "breakout"
    assert c.stop_pct == pytest.approx(CFG.stop_atr_mult * 0.02)
    assert c.take_profit_pct == pytest.approx(CFG.take_profit_atr_mult * 0.02)
    assert c.max_holding_minutes == CFG.max_holding_minutes


def test_breakout_short_after_a_recent_squeeze():
    at = N - 1 - CFG.compression_lookback_bars // 2
    widths = flat_with_squeeze(squeeze_at=at)
    view, t = make_window(widths, donchian=0.0)
    c = S.evaluate(view, t)
    assert c is not None and c.direction == -1


def test_no_candidate_without_a_donchian_extreme():
    at = N - 1 - CFG.compression_lookback_bars // 2
    widths = flat_with_squeeze(squeeze_at=at)
    view, t = make_window(widths, donchian=0.5)
    assert S.evaluate(view, t) is None


def test_no_candidate_without_a_recent_squeeze_even_with_a_donchian_extreme():
    widths = flat_with_squeeze()  # no squeeze anywhere
    view, t = make_window(widths, donchian=1.0)
    assert S.evaluate(view, t) is None


def test_squeeze_outside_the_lookback_window_does_not_count():
    at = N - 1 - CFG.compression_lookback_bars - 5  # before the lookback window starts
    widths = flat_with_squeeze(squeeze_at=at)
    view, t = make_window(widths, donchian=1.0)
    assert S.evaluate(view, t) is None


def test_squeeze_at_the_current_bar_itself_does_not_count():
    """The percentile threshold and the squeeze check both exclude the current bar: today's own extreme
    value can't set its own bar (that would be circular, not a "recent squeeze before the breakout")."""
    widths = flat_with_squeeze()
    widths[-1] = 0.001  # an extreme low width, but on the breakout bar itself
    view, t = make_window(widths, donchian=1.0)
    assert S.evaluate(view, t) is None


def test_insufficient_history_gives_no_signal():
    rows = [{"h1_bb_width": 0.05, "h1_donchian_pos_24": 1.0, "h1_atr_pct": 0.02}] * (N - 1)
    view, t = view_rows(rows)
    assert S.evaluate(view, t) is None


def test_nan_in_the_window_gives_no_signal():
    widths = flat_with_squeeze(squeeze_at=N - 5)
    widths[10] = float("nan")
    view, t = make_window(widths, donchian=1.0)
    assert S.evaluate(view, t) is None


def test_strength_increases_with_breakout_distance_and_is_clamped():
    at = N - 1 - CFG.compression_lookback_bars // 2
    widths = flat_with_squeeze(squeeze_at=at)
    view_edge, t_edge = make_window(widths, donchian=CFG.breakout_upper)
    view_far, t_far = make_window(widths, donchian=1.0)
    c_edge = S.evaluate(view_edge, t_edge)
    c_far = S.evaluate(view_far, t_far)
    assert c_edge.strength == pytest.approx(0.0, abs=1e-9)
    assert c_far.strength == pytest.approx(1.0)
