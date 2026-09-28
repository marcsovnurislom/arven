"""Config, Signal, MarketData, costs and margin functions."""

import copy

import numpy as np
import pytest
import yaml
from bt_helpers import HOUR, T0, app_config, bt_config, make_market
from pydantic import ValidationError

from arven.backtest.costs import adverse_price, require_taker_only, slippage_fraction, taker_fee_rate
from arven.backtest.errors import ConfigurationError, DataError
from arven.backtest.margin import initial_margin, liquidation_price, liquidation_price_from_margin, qty_from_notional
from arven.backtest.marketdata import MINUTE_MS, MarketData, align_funding, funding_grid
from arven.core.backtest_config import BACKTEST_FILE, BacktestConfig, load_backtest_config
from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.signal import Signal
from arven.core.types import Action


# --- BacktestConfig -----------------------------------------------------------------------------


def raw():
    return yaml.safe_load((DEFAULT_CONFIG_DIR / BACKTEST_FILE).read_text(encoding="utf-8"))


def test_repo_backtest_config_loads_with_documented_defaults():
    cfg = load_backtest_config()
    assert (cfg.initial_equity_usdt, cfg.leverage, cfg.maintenance_margin_rate) == (10_000.0, 3.0, 0.004)
    assert (cfg.qty_step_btc, cfg.min_notional_usdt, cfg.latency_minutes) == (0.001, 100.0, 0)
    assert cfg.baselines.random_entry.n_seeds == 200 and cfg.latency_ms == 0
    assert cfg.config_hash() == load_backtest_config().config_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(maintenance_margin_rate=0.4),  # >= 1 / leverage
        lambda d: d.update(latency_minutes=60),
        lambda d: d.update(latency_minutes=-1),
        lambda d: d.update(leverage=0.5),
        lambda d: d.update(margin_mode="cross"),
        lambda d: d.update(unknown=1),
        lambda d: d.pop("liquidation_includes_funding"),
        lambda d: d["baselines"]["random_entry"].update(direction_mode="momentum"),
        lambda d: d.update(initial_equity_usdt=0),
    ],
)
def test_invalid_backtest_config_is_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        BacktestConfig.model_validate(doc)


def test_config_hash_changes_with_any_value():
    doc = raw()
    doc["leverage"] = 2.0
    assert BacktestConfig.model_validate(doc).config_hash() != load_backtest_config().config_hash()


# --- Signal -------------------------------------------------------------------------------------


def test_signal_validation():
    Signal(T0, Action.LONG, notional_fraction=0.5, stop_pct=0.01, take_profit_pct=0.02, max_holding_minutes=60, tag="x")
    Signal(T0, Action.NO_TRADE)
    Signal(T0, Action.NO_TRADE, close_position=True)
    for kwargs in (
        dict(action=Action.LONG),  # no size
        dict(action=Action.LONG, notional_fraction=0.0),
        dict(action=Action.SHORT, notional_fraction=float("nan")),
        dict(action=Action.NO_TRADE, notional_fraction=0.5),
        dict(action=Action.LONG, notional_fraction=1.0, close_position=True),
        dict(action=Action.LONG, notional_fraction=1.0, stop_pct=1.5),
        dict(action=Action.LONG, notional_fraction=1.0, take_profit_pct=-0.1),
        dict(action=Action.LONG, notional_fraction=1.0, max_holding_minutes=0),
    ):
        with pytest.raises(ValueError):
            Signal(T0, **kwargs)


# --- costs and margin ---------------------------------------------------------------------------


def test_cost_functions_hand_values():
    costs = app_config().costs
    assert taker_fee_rate(costs) == pytest.approx(5e-4)
    assert slippage_fraction(30_000.0, 30_000.0, 30_000.0, costs, False) == pytest.approx(1e-4)
    # range 30 / 30 000 = 10 bps -> 1 + 0.1 * 10 = 2 bps; stress x2 = 4 bps
    assert slippage_fraction(30_000.0, 30_030.0, 30_000.0, costs, False) == pytest.approx(2e-4)
    assert slippage_fraction(30_000.0, 30_030.0, 30_000.0, costs, True) == pytest.approx(4e-4)
    assert adverse_price(100.0, 1, 0.01) == pytest.approx(101.0) and adverse_price(100.0, -1, 0.01) == pytest.approx(99.0)
    require_taker_only(costs)
    with pytest.raises(ConfigurationError):
        require_taker_only(app_config(fees={"exit_order_type": "maker"}).costs)


def test_margin_functions_hand_values():
    assert initial_margin(9_000.0, 3.0) == 3_000.0
    assert liquidation_price(1, 30_000.0, 3.0, 0.004) == pytest.approx(30_000 * (2 / 3) / 0.996)
    assert liquidation_price(-1, 30_000.0, 3.0, 0.004) == pytest.approx(30_000 * (4 / 3) / 1.004)
    q, e, lev = 0.333, 30_000.0, 3.0
    for side in (1, -1):
        assert liquidation_price_from_margin(side, e, q, q * e / lev, 0.004) == pytest.approx(liquidation_price(side, e, lev, 0.004))
    # funding that eats the margin pushes the long liquidation price up towards the entry
    assert liquidation_price_from_margin(1, e, q, 0.5 * q * e / lev, 0.004) > liquidation_price(1, e, lev, 0.004)
    assert qty_from_notional(4_980.0, 30_003.0, 0.001) == pytest.approx(0.165)
    assert qty_from_notional(10.0, 30_000.0, 0.001) == 0.0


# --- MarketData ---------------------------------------------------------------------------------


def bars(n=5, start=T0):
    t = start + np.arange(n, dtype=np.int64) * MINUTE_MS
    o = np.full(n, 100.0)
    return dict(time_ms=t, open=o, high=o + 1, low=o - 1, close=o)


def build(**over):
    b = bars()
    b.update(over)
    return MarketData(b["time_ms"], b["open"], b["high"], b["low"], b["close"], T0, T0 + HOUR, np.array([], dtype=np.int64), np.array([]), 8 * HOUR)


def test_marketdata_lookup_gaps_and_fingerprint():
    md = make_market(1, drop_minutes={10, 11})
    assert md.index_of(T0) == 0 and md.index_of(T0 + 10 * MINUTE_MS) == -1 and md.first_at_or_after(T0 + 10 * MINUTE_MS) == 10
    assert list(md.gap_indices) == [10]
    assert md.fingerprint() == make_market(1, drop_minutes={10, 11}).fingerprint()
    assert md.fingerprint() != make_market(1, drop_minutes={10}).fingerprint()
    assert len(md) == 58


@pytest.mark.parametrize(
    "over",
    [
        dict(time_ms=bars()["time_ms"][::-1].copy()),
        dict(time_ms=bars()["time_ms"] + 1),  # not aligned to the minute
        dict(high=np.full(5, 99.0)),  # high < low
        dict(low=np.full(5, 0.0)),
        dict(open=np.array([100.0, 100.0, np.nan, 100.0, 100.0])),
        dict(close=np.full(5, 500.0)),  # close above high
    ],
)
def test_invalid_market_data_is_refused(over):
    with pytest.raises(DataError):
        build(**over)


def test_bars_outside_the_window_are_refused():
    with pytest.raises(DataError):
        MarketData(*[a for a in bars(3, T0 + HOUR).values()], T0, T0 + HOUR, np.array([], dtype=np.int64), np.array([]), 8 * HOUR)


def test_funding_alignment_puts_nan_where_a_rate_is_missing_and_rejects_off_grid_times():
    eight = 8 * HOUR
    start, end = T0, T0 + 24 * HOUR
    grid, rates = align_funding(np.array([T0 + eight]), np.array([0.001]), start, end, eight)
    assert list(grid) == [T0, T0 + eight, T0 + 2 * eight] and np.isnan(rates[0]) and rates[1] == 0.001 and np.isnan(rates[2])
    with pytest.raises(DataError):
        align_funding(np.array([T0 + HOUR]), np.array([0.001]), start, end, eight)
    assert list(funding_grid(T0 + 1, end, eight)) == [T0 + eight, T0 + 2 * eight]
    # rows outside the window are ignored, never leaked in
    g, r = align_funding(np.array([T0 - eight, T0 + 3 * eight]), np.array([1.0, 2.0]), start, end, eight)
    assert np.isnan(r).all()


def test_funding_bar_index_maps_funding_times_to_bars():
    md = make_market(9, funding_rates={T0 + 8 * HOUR: 0.0001}, drop_minutes=set())
    assert list(md.funding_bar_index) == [0, 480]
    md2 = make_market(9, funding_rates={T0 + 8 * HOUR: 0.0001}, drop_minutes={480})
    assert list(md2.funding_bar_index) == [0, -1]


def test_default_repo_backtest_config_matches_helper_defaults():
    assert bt_config().model_dump() == load_backtest_config().model_dump()
