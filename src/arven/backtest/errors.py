"""Backtest exceptions."""


class BacktestError(Exception):
    """Base class."""


class ConfigurationError(BacktestError):
    """A configuration the Stage 4 engine does not support or that is inconsistent."""


class DataError(BacktestError):
    """Market data violates a requirement (invalid OHLC, missing funding while in a position, ...)."""


class SignalError(BacktestError):
    """A provider returned an invalid signal (wrong time, ...)."""


class LookAheadError(BacktestError):
    """A provider tried to read data from after the current decision time."""
