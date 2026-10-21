"""Holiday matching of scripts/research/gold_closures.py (the derivation of config/sessions/cme_metals_closures.csv)."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research"))

import gold_closures as gc  # noqa: E402

from arven.core.time import UTC, to_ms  # noqa: E402


def _closure(start: datetime, end: datetime) -> tuple[date, str] | None:
    s, e = to_ms(start), to_ms(end)
    return gc.holiday_of(s, e - s)


def test_christmas_observed_on_the_24th_is_not_overwritten_by_the_eve():
    assert gc.us_holidays(2021)[date(2021, 12, 24)] == "Christmas"  # 25th was a Saturday
    assert gc.us_holidays(2025)[date(2025, 12, 24)] == "Christmas Eve"


def test_friday_to_monday_closure_belongs_to_the_monday_holiday_not_a_sunday_eve():
    # 2023: Christmas Eve and New Year's Eve were Sundays; CME was shut Fri 17:00 ET -> Mon 17:00 ET
    assert _closure(datetime(2023, 12, 22, 22, tzinfo=UTC), datetime(2023, 12, 25, 22, tzinfo=UTC)) == (date(2023, 12, 25), "Christmas")
    assert _closure(datetime(2023, 12, 29, 22, tzinfo=UTC), datetime(2024, 1, 1, 22, tzinfo=UTC)) == (date(2024, 1, 1), "New Year's Day")


def test_weekday_holidays_still_match():
    assert _closure(datetime(2025, 7, 4, 17, tzinfo=UTC), datetime(2025, 7, 4, 21, tzinfo=UTC)) == (date(2025, 7, 4), "Independence Day")
    assert _closure(datetime(2021, 12, 23, 22, tzinfo=UTC), datetime(2021, 12, 24, 22, tzinfo=UTC)) == (date(2021, 12, 24), "Christmas")
