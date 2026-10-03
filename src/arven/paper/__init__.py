"""Stage 8: the paper-signal loop (real, forward-only, simulated-fill trading on live data).

Reuses Stage 4-7 unchanged: the same ``Backtester``/``Simulator``/``Stage5Pipeline`` that run a backtest run
the forward period too (CLAUDE.md rule 8 - one code path for backtest and live), the only difference being
the data source (REST-updated, growing) and the period (``BacktestPeriod.FORWARD``, no fixed end). No real
order execution, no private API keys (CLAUDE.md rule 12) - every fill is the same simulated fill model Stage
4 already uses, just applied going forward in real time instead of over sealed history.
"""
