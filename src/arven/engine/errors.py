"""Engine exceptions.

``LookAheadError`` is the same concept as ``arven.backtest.errors.LookAheadError`` but defined here, because
``arven.engine`` must never import ``arven.backtest`` (module boundary, ``tests/engine/test_engine_static_rules.py``).
"""


class LookAheadError(Exception):
    """A requested value could only be produced from data that was not yet available at the decision time
    (for example: no closed bar of a requested timeframe exists at or before ``t``)."""
