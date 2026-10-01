"""resolve_window_for_fold's dev/validation/boundary-crossing cases, and regime-hysteresis-state-reset
across walk-forward window boundaries (spec requirement 14).
"""

import pytest
from pipeline_helpers import make_feature_data, random_1m_market

from arven.backtest.engine import Backtester
from arven.core.backtest_config import load_backtest_config
from arven.core.config import load_config
from arven.core.regime_config import load_regime_config
from arven.core.risk_config import load_risk_config
from arven.core.splitguard import BacktestPeriod, SplitGuard
from arven.core.strategies_config import load_strategies_config
from arven.decision.pipeline import Stage5Pipeline
from arven.ml.splits import Fold
from arven.wfo import resolve_window_for_fold

REGIME, STRATEGIES, RISK, BT, APP = (
    load_regime_config(), load_strategies_config(), load_risk_config(), load_backtest_config(), load_config(),
)
HOUR = 3_600_000


def _guard():
    return SplitGuard(APP.splits)


def test_a_window_entirely_inside_development_resolves_to_development():
    guard = _guard()
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    fold = Fold(0, dev.start_ms, dev.start_ms + 100 * HOUR, dev.start_ms + 50 * HOUR, dev.start_ms + 100 * HOUR)
    window = resolve_window_for_fold(guard, fold)
    assert window is not None and window.period.value == "development"
    assert window.start_ms == fold.valid_start_ms and window.end_ms == fold.valid_end_ms


def test_a_window_entirely_inside_validation_resolves_to_validation():
    guard = _guard()
    val = guard.resolve(BacktestPeriod.VALIDATION)
    fold = Fold(0, val.start_ms, val.start_ms + 100 * HOUR, val.start_ms + 50 * HOUR, val.start_ms + 100 * HOUR)
    window = resolve_window_for_fold(guard, fold)
    assert window is not None and window.period.value == "validation"


def test_a_window_straddling_the_dev_val_boundary_is_unbacktestable():
    guard = _guard()
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    fold = Fold(0, dev.start_ms, dev.end_ms + 10 * HOUR, dev.end_ms - 10 * HOUR, dev.end_ms + 10 * HOUR)
    assert resolve_window_for_fold(guard, fold) is None


def test_the_real_fold_10_is_the_one_boundary_crossing_window():
    """Confirms, on the real schedule, that exactly the documented window (index 10) straddles the
    boundary and no other window does."""
    from arven.core.ml_config import load_ml_config
    from arven.ml.splits import generate_folds

    ml_cfg = load_ml_config()
    guard = _guard()
    dev, val = guard.resolve(BacktestPeriod.DEVELOPMENT), guard.resolve(BacktestPeriod.VALIDATION)
    folds = generate_folds(dev.start_ms, val.end_ms, ml_cfg.walk_forward.min_train_months, ml_cfg.walk_forward.retrain_interval_months)
    crossing = [f.fold_index for f in folds if resolve_window_for_fold(guard, f) is None]
    assert crossing == [10]


@pytest.mark.parametrize("seed", [1, 2])
def test_regime_hysteresis_state_does_not_carry_across_walk_forward_window_boundaries(seed):
    """Spec requirement 14: a window's regime classification sequence must be identical whether or not a
    DIFFERENT, earlier window was processed first on a pipeline object that gets reused-in-principle - i.e.
    Stage5Pipeline.prepare() (called by every Backtester.run()) must fully reset hysteresis/risk state, so
    two structurally different orchestration strategies (always-fresh-pipeline vs reuse-then-reset) agree."""
    days = 300
    guard = _guard()
    dev = guard.resolve(BacktestPeriod.DEVELOPMENT)
    feats = make_feature_data(days, seed, start_ms=dev.start_ms)
    market = random_1m_market(days * 24, seed, start_ms=dev.start_ms)

    cut = days * 24 * HOUR // 2
    window_a = guard.resolve(BacktestPeriod.DEVELOPMENT, dev.start_ms, dev.start_ms + cut)
    window_b = guard.resolve(BacktestPeriod.DEVELOPMENT, dev.start_ms + cut, dev.start_ms + days * 24 * HOUR)

    def slice_market(md, start_ms, end_ms):
        import numpy as np

        from arven.backtest.marketdata import MarketData

        mask = (md.time_ms >= start_ms) & (md.time_ms < end_ms)
        fmask = (md.funding_time_ms >= start_ms) & (md.funding_time_ms < end_ms)
        return MarketData(md.time_ms[mask], md.open[mask], md.high[mask], md.low[mask], md.close[mask],
                           start_ms, end_ms, md.funding_time_ms[fmask], md.funding_rate[fmask], md.funding_interval_ms)

    def slice_features(fd, start_ms, end_ms):
        import numpy as np

        from arven.backtest.provider import FeatureData

        mask = (fd.t_ms >= start_ms) & (fd.t_ms < end_ms)
        return FeatureData(fd.t_ms[mask], fd.names, fd.values[mask], fd.first_ready_ms)

    market_b = slice_market(market, window_b.start_ms, window_b.end_ms)
    feats_b = slice_features(feats, window_b.start_ms, window_b.end_ms)

    # Strategy 1: process window A first (fresh pipeline), then window B on a SECOND fresh pipeline.
    market_a = slice_market(market, window_a.start_ms, window_a.end_ms)
    feats_a = slice_features(feats, window_a.start_ms, window_a.end_ms)
    pipeline_1 = Stage5Pipeline(REGIME, STRATEGIES, RISK, BT)
    Backtester(APP, BT, window_a, market_a, feats_a).run(pipeline_1)
    pipeline_2 = Stage5Pipeline(REGIME, STRATEGIES, RISK, BT)
    result_after_a = Backtester(APP, BT, window_b, market_b, feats_b).run(pipeline_2)
    regimes_after_a = [r.regime for r in pipeline_2.history]

    # Strategy 2: process window B in complete isolation, nothing run before it.
    pipeline_3 = Stage5Pipeline(REGIME, STRATEGIES, RISK, BT)
    result_isolated = Backtester(APP, BT, window_b, market_b, feats_b).run(pipeline_3)
    regimes_isolated = [r.regime for r in pipeline_3.history]

    assert regimes_after_a == regimes_isolated
    assert [t.entry_time_ms for t in result_after_a.trades] == [t.entry_time_ms for t in result_isolated.trades]
    assert [t.net_pnl for t in result_after_a.trades] == [t.net_pnl for t in result_isolated.trades]
