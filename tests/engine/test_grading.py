import pytest

from arven.engine.grading import Grade, TrackRecord, grade, is_suspended, is_validated

GOOD = dict(
    wfo_window_total_returns=(0.1, 0.2, -0.05, 0.03, 0.15),  # 4/5 positive -> majority
    n_simulated_trades=150,
    beats_no_trade=True,
    beats_buy_and_hold=True,
    beats_random_entry=True,
    survives_cost_stress=True,
    n_forward_trades=40,
    forward_net_expectancy_r=0.05,
)


def tr(**over):
    base = dict(GOOD)
    base.update(over)
    return TrackRecord(**base)


def test_a_fully_qualifying_record_is_validated():
    assert grade(tr()) == Grade.VALIDATED
    assert is_validated(tr())


def test_default_with_no_track_record_at_all_is_experimental():
    empty = TrackRecord((), 0, False, False, False, False, 0, 0.0)
    assert grade(empty) == Grade.EXPERIMENTAL


@pytest.mark.parametrize(
    "override",
    [
        dict(wfo_window_total_returns=(-0.1, -0.2, 0.05, 0.01, -0.03)),  # majority negative
        dict(n_simulated_trades=99),  # one short of the minimum
        dict(beats_no_trade=False),
        dict(beats_buy_and_hold=False),
        dict(beats_random_entry=False),
        dict(survives_cost_stress=False),
        dict(n_forward_trades=29),  # one short of the minimum
        dict(forward_net_expectancy_r=-0.001),
    ],
)
def test_failing_any_single_criterion_keeps_it_experimental(override):
    assert grade(tr(**override)) == Grade.EXPERIMENTAL


def test_exactly_the_minimums_still_qualifies():
    assert grade(tr(n_simulated_trades=100, n_forward_trades=30, forward_net_expectancy_r=0.0)) == Grade.VALIDATED


def test_a_tied_majority_is_not_a_majority():
    # 2 of 4 positive is not "majority positive" (needs strictly more than half).
    assert grade(tr(wfo_window_total_returns=(0.1, 0.1, -0.1, -0.1))) == Grade.EXPERIMENTAL


def test_rolling_expectancy_below_threshold_suspends():
    record = tr(rolling_30_trade_expectancy_r=-0.31)
    assert is_suspended(record)
    assert grade(record) == Grade.SUSPENDED


def test_rolling_expectancy_at_exactly_the_threshold_does_not_suspend():
    assert grade(tr(rolling_30_trade_expectancy_r=-0.3)) == Grade.VALIDATED


def test_drawdown_above_threshold_suspends():
    record = tr(max_drawdown_r=8.1)
    assert is_suspended(record)
    assert grade(record) == Grade.SUSPENDED


def test_suspended_overrides_an_otherwise_fully_qualifying_record():
    record = tr(rolling_30_trade_expectancy_r=-1.0)
    assert grade(record) == Grade.SUSPENDED  # not VALIDATED, even though every other criterion holds


def test_none_rolling_expectancy_and_drawdown_never_suspend_on_their_own():
    assert grade(tr(rolling_30_trade_expectancy_r=None, max_drawdown_r=None)) == Grade.VALIDATED


def test_rejects_negative_trade_counts():
    with pytest.raises(ValueError):
        tr(n_simulated_trades=-1)


def test_rejects_non_finite_expectancy():
    with pytest.raises(ValueError):
        tr(forward_net_expectancy_r=float("nan"))
