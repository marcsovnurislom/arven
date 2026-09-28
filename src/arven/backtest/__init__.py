"""Deterministic 1m execution backtester (Stage 4).

Pure numpy/stdlib: no I/O, no database, no strategy / risk / ML code. Data and features arrive as typed
objects built by the composition root (``arven.cli``); the engine consumes a ``SignalProvider`` and
returns a ``BacktestResult``. Boundaries are enforced by ``tests/backtest/test_static_rules.py``.
"""
