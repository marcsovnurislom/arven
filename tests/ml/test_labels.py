"""Triple-barrier labels: hand-computed cases."""

import pytest
from bt_helpers import HOUR, T0, app_config, make_market

from arven.ml.labels import resolve_triple_barrier

REAL_COSTS = app_config()  # 5 bps taker, 1 bp fixed slippage, 0.1 x range
ZERO_COSTS = app_config(fees={"taker_fee_bps": 0.0}, slippage={"fixed_bps": 0.0, "volatility_multiplier": 0.0})


def test_take_profit_hit_zero_costs():
    bars = {65: (30_600.0, 30_600.0, 30_600.0, 30_600.0)}  # flat bar exactly at the TP level (entry 30 000 * 1.02)
    market = make_market(5, bars)
    r = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    assert r.outcome == "TP" and r.label == 1
    assert r.entry_price == pytest.approx(30_000.0) and r.exit_price == pytest.approx(30_600.0)
    assert r.net_return == pytest.approx(0.02, rel=1e-9)


def test_stop_hit_zero_costs():
    bars = {70: (30_000.0, 30_310.0, 30_000.0, 30_200.0)}
    market = make_market(5, bars)
    r = resolve_triple_barrier(market, T0 + HOUR, -1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    assert r.outcome == "SL" and r.label == 0
    assert r.exit_ref_price == pytest.approx(30_300.0)
    assert r.net_return == pytest.approx((30_000.0 - 30_300.0) / 30_000.0, rel=1e-9)


def test_time_barrier_no_touch():
    market = make_market(4)  # flat market, never touches either barrier
    r = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 90, ZERO_COSTS.costs, 0.0)
    assert r.outcome == "TIME" and r.label == 0
    assert r.exit_time_ms == T0 + HOUR + 90 * 60_000


def test_same_bar_tie_stop_wins():
    bars = {80: (30_000.0, 31_000.0, 29_000.0, 30_000.0)}  # touches both 29 700 and 30 600
    market = make_market(5, bars)
    r = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    assert r.outcome == "SL"


def test_barrier_can_trigger_on_the_fill_bar_itself():
    bars = {60: (30_000.0, 30_700.0, 30_000.0, 30_000.0)}  # the fill bar itself touches TP intrabar
    market = make_market(5, bars)
    r = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    assert r.outcome == "TP" and r.exit_time_ms == T0 + HOUR


def test_short_direction_mirrors_long():
    bars = {65: (29_400.0, 29_400.0, 29_400.0, 29_400.0)}  # TP for a short is a lower price
    market = make_market(5, bars)
    r = resolve_triple_barrier(market, T0 + HOUR, -1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    assert r.outcome == "TP" and r.label == 1


def test_net_of_costs_flips_a_marginal_take_profit_to_label_zero():
    bars = {65: (30_603.06, 30_603.06, 30_603.06, 30_603.06)}
    market = make_market(5, bars)
    r_zero = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    r_real = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, REAL_COSTS.costs, 0.0)
    assert r_zero.label == 1
    assert r_real.net_return < r_zero.net_return  # costs erode the same gross outcome
    r_strict = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.05)
    assert r_strict.outcome == "TP" and r_strict.label == 0  # TP-first but below the required min net return


def test_missing_fill_bar_is_not_eligible():
    market = make_market(5, drop_minutes={60})
    r = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    assert r is None


def test_horizon_beyond_stored_data_is_not_eligible():
    market = make_market(3)  # 3 hours of data; ask for a 24h horizon from near the end
    r = resolve_triple_barrier(market, T0 + 2 * HOUR, 1, 0.01, 0.02, 24 * 60, ZERO_COSTS.costs, 0.0)
    assert r is None


def test_gap_through_stop_labels_at_the_barrier_not_the_gapped_price():
    """Documented simplification (see labels.py docstring): the label uses the barrier level itself, not
    the worse gapped-through price a real fill would get."""
    bars = {90: (29_500.0, 29_600.0, 29_400.0, 29_450.0)}  # opens below the 29 700 stop
    market = make_market(5, bars)
    r = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, ZERO_COSTS.costs, 0.0)
    assert r.exit_ref_price == pytest.approx(29_700.0)  # the barrier level, not 29 500 (the real gapped open)


def test_rejects_invalid_inputs():
    market = make_market(3)
    with pytest.raises(ValueError):
        resolve_triple_barrier(market, T0 + HOUR, 0, 0.01, 0.02, 60, ZERO_COSTS.costs, 0.0)
    with pytest.raises(ValueError):
        resolve_triple_barrier(market, T0 + HOUR, 1, -0.01, 0.02, 60, ZERO_COSTS.costs, 0.0)
    with pytest.raises(ValueError):
        resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.0, 60, ZERO_COSTS.costs, 0.0)


def test_entry_and_exit_slippage_use_their_own_bars_range():
    bars = {60: (30_000.0, 30_030.0, 30_000.0, 30_000.0), 65: (30_603.06, 30_603.06, 30_603.06, 30_603.06)}
    market = make_market(5, bars)
    r = resolve_triple_barrier(market, T0 + HOUR, 1, 0.01, 0.02, 180, REAL_COSTS.costs, 0.0)
    # entry bar range 30/30000 = 10 bps -> sigma = (1 + 0.1*10) bps = 2 bps
    assert r.entry_price == pytest.approx(30_000.0 * (1 + 2e-4))
    # exit bar is flat -> sigma = fixed 1 bp only
    assert r.exit_price == pytest.approx(30_603.06 * (1 - 1e-4))
