"""The multi-timeframe event-driven engine (`docs/ARVEN_MASTER_PROMPT.md`, phases 1+).

Built *alongside* the existing Stage 1-10 pipeline, not instead of it: nothing here modifies
`arven.backtest.clock.Clock`/`SimulationClock`, `arven.backtest.provider.FeatureView`, or
`arven.decision.pipeline.Stage5Pipeline` - the legacy 1h-only path keeps producing byte-identical results.
(Precisely: the golden value `result_hash 3eca0a70...` exists only in the real local development-backtest
artifacts under the git-ignored `data/` and in `docs/current_state.md`; it is not pinned in the test suite.
What the tests enforce - e.g. `tests/pipeline/test_stage5_no_ml_regression.py` - is equality of
`result_hash` between runs on identical synthetic fixtures.)

Phase 1 scope (this module and its siblings `events.py`, `clock.py`, `spec.py`): the event/type
vocabulary and a simulated clock that orders bar-close events across several timeframes deterministically
and without look-ahead. Phase 2 added per-timeframe feature tables and `MultiTFView` (`features.py`,
`multitf.py`, `errors.py`).

Module boundary: this package depends only on `arven.core` and the generic `arven.features.indicators`/
`arven.features.asof` primitives, never on `decision`/`risk`/`strategies`/`regime`/`backtest` - enforced by
`tests/engine/test_engine_static_rules.py` and `test_engine_phase2_static_rules.py`. Phase 3's event-driven
backtest loop, which must reuse the Stage 4 execution layer unchanged, therefore lives in
`arven.backtest.event_engine` and imports *from* this package (clock/events only): the dependency points
`backtest -> engine`, never the reverse (`tests/backtest/test_event_engine_static_rules.py`).
"""
