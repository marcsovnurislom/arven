import pytest

from arven.core.timeframes import Timeframe
from arven.engine.events import BarCloseEvent

HOUR = 3_600_000


def test_valid_event_constructs():
    e = BarCloseEvent("BTCUSDT", Timeframe.H1, 0, HOUR, HOUR)
    assert e.symbol == "BTCUSDT" and e.close_ms == HOUR and e.available_at_ms == HOUR


def test_rejects_empty_symbol():
    with pytest.raises(ValueError):
        BarCloseEvent("", Timeframe.H1, 0, HOUR, HOUR)


def test_rejects_close_ms_not_matching_open_plus_duration():
    with pytest.raises(ValueError):
        BarCloseEvent("BTCUSDT", Timeframe.H1, 0, HOUR + 1, HOUR + 1)


def test_rejects_available_at_before_close():
    with pytest.raises(ValueError):
        BarCloseEvent("BTCUSDT", Timeframe.H1, 0, HOUR, HOUR - 1)


def test_available_at_may_equal_or_exceed_close():
    BarCloseEvent("BTCUSDT", Timeframe.H1, 0, HOUR, HOUR)  # equal: ok
    BarCloseEvent("BTCUSDT", Timeframe.H1, 0, HOUR, HOUR + 60_000)  # later: ok
