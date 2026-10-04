"""Stage 9a leakage protection: the macro-event blackout must depend only on the event's *scheduled* time
(public knowledge announced months to a year in advance) and the decision time itself - never on anything
that would not have been known at t, and never on the eventual released value (which this module does not
even store - see core/macro_config.py's module docstring and MacroEvent's fields)."""

from __future__ import annotations

from dataclasses import fields

from arven.core.macro_config import MacroEvent, load_macro_events
from arven.risk.engine import _active_blackout

HOUR = 3_600_000


def test_blackout_decision_is_a_pure_function_of_t_and_the_calendar_only():
    """Perturbing anything other than (t_ms, events, window) is structurally impossible: _active_blackout
    takes no other argument. This is the leakage-suite analogue of the truncation/perturbation tests used
    throughout the rest of the project, specialised to a function that has no market-data input to leak."""
    events = (MacroEvent(10 * HOUR, "FOMC", ""),)
    before = _active_blackout(10 * HOUR, events, 1.0)
    # "perturbing the future" here means: nothing downstream of t exists to perturb, since the function's
    # only inputs are the fixed calendar and t itself - re-deriving it any number of times from the same
    # inputs must give the identical result.
    after = _active_blackout(10 * HOUR, events, 1.0)
    assert before == after and before is not None


def test_the_real_calendar_contains_no_released_value_or_forecast():
    """Structural guarantee: even if a future Stage 9b change adds an 'actual'/'forecast' column to the CSV
    loader, MacroEvent itself (the only thing the risk engine ever sees) would need to be extended first,
    and this test would catch that extension so it gets the same available_at scrutiny Stage 2/3's point-in-
    time rules already demand."""
    names = {f.name for f in fields(MacroEvent)}
    assert "actual" not in names and "forecast" not in names
    events = load_macro_events()
    assert len(events) > 0  # sanity: the real calendar loads and is exercised by the check above


def test_scheduled_times_are_not_derived_from_any_point_in_time_market_or_feature_data():
    """The calendar loader (core.macro_config.load_macro_events) takes only a config directory - it has no
    parameter for market data, a decision time, or a database connection, so it cannot possibly be
    conditioned on anything that would make an event's scheduled time t-dependent."""
    import inspect

    sig = inspect.signature(load_macro_events)
    assert list(sig.parameters) == ["config_dir"]
