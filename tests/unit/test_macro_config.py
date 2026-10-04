"""Macro calendar loader: DST-aware ET->UTC conversion (hand-computed against the fixed US DST rule), CSV
parsing, and the no-actual-values structural guarantee that makes rule 2 leakage-free."""

from __future__ import annotations

from dataclasses import fields
from datetime import date

import pytest

from arven.core.macro_config import (
    MacroEvent,
    load_macro_events,
    macro_events_hash,
    us_eastern_utc_offset_hours,
)
from arven.core.time import from_ms


# --- DST offset: hand-computed against the fixed US rule (2nd Sunday of March .. 1st Sunday of November) ---


@pytest.mark.parametrize(
    "d,expected",
    [
        (date(2020, 1, 29), -5),   # winter: EST
        (date(2020, 3, 7), -5),    # the day before the 2020 DST start (2nd Sunday of March = Mar 8) - EST
        (date(2020, 3, 8), -4),    # 2020 DST start itself - EDT from this day (release times are after 2am)
        (date(2020, 10, 31), -4),  # the day before DST ends - still EDT
        (date(2020, 11, 1), -5),   # 2020 DST end itself (1st Sunday of November) - EST from this day
        (date(2020, 11, 2), -5),   # the day after - still EST
        (date(2024, 3, 9), -5),    # 2024 DST starts Mar 10 (2nd Sunday) - Mar 9 still EST
        (date(2024, 3, 10), -4),
        (date(2026, 3, 7), -5),    # 2026 DST starts Mar 8 (2nd Sunday, since Mar 1 2026 is a Sunday) - Mar 7 still EST
        (date(2026, 3, 8), -4),
    ],
)
def test_us_eastern_offset_matches_the_fixed_dst_rule(d, expected):
    assert us_eastern_utc_offset_hours(d) == expected


def test_dst_start_and_end_are_both_second_and_first_sunday_respectively():
    # 2026: 2nd Sunday of March is Mar 8; 1st Sunday of November is Nov 1.
    assert us_eastern_utc_offset_hours(date(2026, 3, 7)) == -5
    assert us_eastern_utc_offset_hours(date(2026, 3, 8)) == -4
    assert us_eastern_utc_offset_hours(date(2026, 10, 31)) == -4
    assert us_eastern_utc_offset_hours(date(2026, 11, 1)) == -5


# --- the real calendar ---------------------------------------------------------------------------


def test_the_real_calendar_loads_sorted_and_deduplicated_in_time():
    events = load_macro_events()
    assert len(events) > 0
    times = [e.scheduled_at_ms for e in events]
    assert times == sorted(times)
    assert len(set((e.scheduled_at_ms, e.event_type) for e in events)) == len(events)


def test_every_row_is_one_of_the_three_in_scope_event_types():
    events = load_macro_events()
    assert {e.event_type for e in events} <= {"FOMC", "CPI", "NFP"}


def test_a_known_fomc_statement_time_converts_correctly_in_winter_and_summer():
    events = load_macro_events()
    jan_2020 = next(e for e in events if e.event_type == "FOMC" and from_ms(e.scheduled_at_ms).date() == date(2020, 1, 29))
    assert from_ms(jan_2020.scheduled_at_ms).hour == 19  # 14:00 EST -> 19:00 UTC
    jul_2020 = next(e for e in events if e.event_type == "FOMC" and from_ms(e.scheduled_at_ms).date() == date(2020, 7, 29))
    assert from_ms(jul_2020.scheduled_at_ms).hour == 18  # 14:00 EDT -> 18:00 UTC


def test_the_calendar_covers_at_least_the_full_project_history_and_the_current_forward_period():
    events = load_macro_events()
    first, last = from_ms(events[0].scheduled_at_ms), from_ms(events[-1].scheduled_at_ms)
    assert first.date() <= date(2020, 2, 1)
    assert last.date() >= date(2026, 11, 1)


def test_hash_is_deterministic_and_content_sensitive():
    events = load_macro_events()
    assert macro_events_hash(events) == macro_events_hash(events)
    mutated = events[:-1] + (MacroEvent(events[-1].scheduled_at_ms + 1, events[-1].event_type, events[-1].note),)
    assert macro_events_hash(mutated) != macro_events_hash(events)


# --- structural leakage guarantee -----------------------------------------------------------------


def test_macro_event_has_no_actual_or_forecast_field():
    """Rule 2 only ever uses the *scheduled* time (public knowledge well in advance) - MacroEvent must
    structurally have no field for the released value or forecast, so a future Stage 9b change cannot
    accidentally wire an unavailable-at-t value into this rule without that change being obvious here."""
    names = {f.name for f in fields(MacroEvent)}
    assert names == {"scheduled_at_ms", "event_type", "note"}


# --- module boundaries -----------------------------------------------------------------------------


def test_macro_config_never_imports_duckdb_or_market_data_modules():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "src" / "arven" / "core" / "macro_config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    bad = [m for m in imports if m == "duckdb" or m.startswith(("arven.data", "arven.backtest", "arven.features"))]
    assert not bad
