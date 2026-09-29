"""Shared helper for Stage 5 pipeline tests: build independent Stage 3 features and a Stage 4 1m market
(they need not share a price path - these tests check wiring, causality and accounting, not economics; the
real backtest results use the real, mutually consistent development-period data instead), wire a
:class:`~arven.decision.pipeline.Stage5Pipeline` and run it through the real, unmodified Stage 4 engine.
"""

from __future__ import annotations

import numpy as np
import synthetic_market as sm
from bt_helpers import T0, HOUR, bt_config, make_market as bt_make_market, window, zero_cost_app

from arven.backtest.engine import Backtester, BacktestResult
from arven.backtest.provider import FeatureData
from arven.core.backtest_config import BacktestConfig, load_backtest_config
from arven.core.config import AppConfig
from arven.core.regime_config import RegimeConfig, load_regime_config
from arven.core.risk_config import RiskConfig, load_risk_config
from arven.core.strategies_config import StrategiesConfig, load_strategies_config
from arven.decision.pipeline import Stage5Pipeline
from arven.features.builder import build_features, decision_grid
from arven.core.features_config import load_features_config


def make_feature_data(days: int, seed: int, start_ms: int = T0) -> FeatureData:
    market3 = sm.make_market(n_days=days, seed=seed)
    fcfg = load_features_config()
    grid = decision_grid(start_ms, start_ms + days * 24 * HOUR)
    table = build_features(market3, grid, fcfg)
    names = tuple(table.columns)
    values = np.column_stack([table.columns[n] for n in names])
    return FeatureData(table.t_ms, names, values, None)


def make_pipeline(
    regime_cfg: RegimeConfig | None = None,
    strategies_cfg: StrategiesConfig | None = None,
    risk_cfg: RiskConfig | None = None,
    bt_cfg: BacktestConfig | None = None,
) -> Stage5Pipeline:
    return Stage5Pipeline(
        regime_cfg or load_regime_config(),
        strategies_cfg or load_strategies_config(),
        risk_cfg or load_risk_config(),
        bt_cfg or load_backtest_config(),
    )


def truncate_features(feats: FeatureData, keep_rows: int) -> FeatureData:
    """The same feature table cut to its first ``keep_rows`` decision times."""
    return FeatureData(feats.t_ms[:keep_rows], feats.names, feats.values[:keep_rows], feats.first_ready_ms)


# Stage 3 guarantees these ranges everywhere (arven.features.checks._BOUNDS); garbage must respect them too,
# or it stops being "different real-looking data" and becomes physically-impossible input no real Stage 3
# build could ever produce - which would trip a strategy's own input validation for reasons unrelated to
# leakage. (name-contains, low, high)
_NONNEGATIVE_OR_BOUNDED = (
    ("_rsi", 0.0, 100.0), ("_adx", 0.0, 100.0), ("_atr_pct", 0.0, None), ("_bb_width", 0.0, None),
    ("_donchian_pos_", 0.0, 1.0), ("_rel_volume", 0.0, None), ("_rel_trades", 0.0, None),
    ("_taker_buy_ratio", 0.0, 1.0), ("_cc_vol_", 0.0, None), ("_parkinson_", 0.0, None), ("_rv_", 0.0, None),
    ("feat_ready", 0.0, 1.0), ("funding_available", 0.0, 1.0), ("oi_available", 0.0, 1.0), ("oi_age_s", 0.0, None),
)


def garbage_features_after(feats: FeatureData, from_row: int, seed: int = 77) -> FeatureData:
    """Same shape, but every row from ``from_row`` on is replaced with random, Stage-3-plausible values."""
    rng = np.random.default_rng(seed)
    values = feats.values.copy()
    n = values.shape[0] - from_row
    for j, name in enumerate(feats.names):
        noise = rng.normal(0.0, 5.0, n)
        for key, lo, hi in _NONNEGATIVE_OR_BOUNDED:
            if key in name:
                noise = abs(noise)
                if hi is not None:
                    noise = lo + (noise % (hi - lo)) if hi > lo else noise
                break
        values[from_row:, j] = noise
    return FeatureData(feats.t_ms, feats.names, values, feats.first_ready_ms)


def random_1m_market(hours: int, seed: int, start_ms: int = T0):
    """A volatile (vectorised) random-walk 1m market, for execution-integration tests that need stops,
    targets and (rarely) liquidations to actually trigger - ``bt_helpers.make_market`` defaults to flat bars."""
    from arven.backtest.marketdata import MINUTE_MS, MarketData, align_funding

    rng = np.random.default_rng(seed)
    n = hours * 60
    vol = float(rng.uniform(0.0006, 0.003))
    close = 30_000.0 * np.exp(np.cumsum(rng.normal(0.0, vol, n)))
    open_ = np.concatenate(([30_000.0], close[:-1]))
    up = np.abs(rng.normal(0.0, vol * 0.5, n))
    down = np.abs(rng.normal(0.0, vol * 0.5, n))
    high = np.maximum(open_, close) * (1 + up)
    low = np.minimum(open_, close) * (1 - down)
    times = start_ms + np.arange(n, dtype=np.int64) * MINUTE_MS
    end_ms = start_ms + hours * HOUR
    interval_ms = 8 * HOUR
    row_t = np.array([start_ms + k * interval_ms for k in range(hours // 8 + 2)], dtype=np.int64)
    row_r = rng.normal(1e-4, 5e-4, len(row_t))
    ft, fr = align_funding(row_t, row_r, start_ms, end_ms, interval_ms)
    return MarketData(times, open_, high, low, close, start_ms, end_ms, ft, fr, interval_ms)


def run_pipeline(
    days: int,
    seed: int = 1,
    market_seed: int = 2,
    app: AppConfig | None = None,
    cfg: BacktestConfig | None = None,
    stress: bool = False,
    start_ms: int = T0,
) -> tuple[BacktestResult, Stage5Pipeline, FeatureData]:
    feats = make_feature_data(days, seed, start_ms)
    market4 = bt_make_market(days * 24, start_ms=start_ms)
    win = window(days * 24, start_ms)
    bt_cfg = cfg or bt_config()
    bt = Backtester(app or zero_cost_app(), bt_cfg, win, market4, feats, stress=stress)
    pipe = make_pipeline(bt_cfg=bt_cfg)
    result = bt.run(pipe)
    return result, pipe, feats
