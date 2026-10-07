"""The multi-timeframe event-driven engine (`docs/ARVEN_MASTER_PROMPT.md`, phases 1+).

Built *alongside* the existing Stage 1-10 pipeline, not instead of it: nothing here modifies
`arven.backtest.clock.Clock`/`SimulationClock`, `arven.backtest.provider.FeatureView`, or
`arven.decision.pipeline.Stage5Pipeline` - the legacy 1h-only path keeps producing byte-identical results
(golden `result_hash 3eca0a70...`, guarded by `tests/pipeline/test_stage5_no_ml_regression.py`).

Phase 1 scope (this module and its siblings `events.py`, `clock.py`, `spec.py`): the event/type
vocabulary and a simulated clock that orders bar-close events across several timeframes deterministically
and without look-ahead. It depends only on `arven.core` (timeframes/time), never on
`decision`/`risk`/`strategies`/`regime`/`backtest` - enforced by a static test, the same pattern used
elsewhere in this project (e.g. `tests/news/test_news_static_rules.py`).
"""
