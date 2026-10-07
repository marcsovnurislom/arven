import pytest

from arven.core.timeframes import Timeframe
from arven.engine.spec import StrategySpec


def make(**over):
    base = dict(
        strategy_id="trend_momentum", version="v1", context_tfs=(Timeframe.H4,),
        setup_tf=Timeframe.H1, trigger_tf=Timeframe.H1, warmup_bars=200,
    )
    base.update(over)
    return StrategySpec(**base)


def test_valid_spec_matching_existing_1h_strategies():
    s = make()
    assert s.trigger_tf == Timeframe.H1 and s.setup_tf == Timeframe.H1 and s.context_tfs == (Timeframe.H4,)


def test_valid_spec_with_different_trigger_and_setup_like_impulse_retest():
    s = make(context_tfs=(Timeframe.H4,), setup_tf=Timeframe.H1, trigger_tf=Timeframe.M15, warmup_bars=50)
    assert s.trigger_tf == Timeframe.M15 and s.setup_tf == Timeframe.H1


def test_empty_context_tfs_is_allowed():
    make(context_tfs=())


def test_rejects_empty_strategy_id():
    with pytest.raises(ValueError):
        make(strategy_id="")


def test_rejects_empty_version():
    with pytest.raises(ValueError):
        make(version="")


def test_rejects_trigger_tf_coarser_than_setup_tf():
    with pytest.raises(ValueError):
        make(setup_tf=Timeframe.M15, trigger_tf=Timeframe.H1)


def test_rejects_context_tf_finer_than_setup_tf():
    with pytest.raises(ValueError):
        make(setup_tf=Timeframe.H1, trigger_tf=Timeframe.H1, context_tfs=(Timeframe.M15,))


def test_rejects_non_positive_warmup_bars():
    with pytest.raises(ValueError):
        make(warmup_bars=0)


def test_allowed_regimes_defaults_to_none_meaning_no_gate():
    assert make().allowed_regimes is None


def test_allowed_regimes_accepts_a_set_of_regime_labels():
    s = make(allowed_regimes=frozenset({"TREND_UP/NORMAL", "TREND_DOWN/NORMAL"}))
    assert s.allowed_regimes == frozenset({"TREND_UP/NORMAL", "TREND_DOWN/NORMAL"})
