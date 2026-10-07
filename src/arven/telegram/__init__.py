"""Phase 6 of `docs/ARVEN_MASTER_PROMPT.md`: Telegram alerts and bot commands.

Message *text* is formatted here from already-computed data (an `EngineSignal`, a `SignalUpdate`, a
heartbeat) - never a trading decision, indicator, price, size or PnL (CLAUDE.md rule 9). This package never
imports `arven.decision`/`arven.risk`/`arven.strategies`/`arven.regime` (enforced by a static test, the
same pattern as `arven.news`/`arven.llm`). It may read `arven.engine` (the signal/grading types it
formats) and `arven.paper` (the heartbeat it reports on) - both read-only.
"""
