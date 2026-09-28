"""Core domain types shared across modules."""

from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    """Final decision-support output. ``NO_TRADE`` is the default."""

    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"

    @property
    def direction(self) -> int:
        """+1 for LONG, -1 for SHORT, 0 for NO_TRADE."""
        return _DIRECTIONS[self]

    @classmethod
    def from_direction(cls, direction: int) -> Action:
        if direction > 0:
            return cls.LONG
        if direction < 0:
            return cls.SHORT
        return cls.NO_TRADE


_DIRECTIONS: dict[Action, int] = {Action.LONG: 1, Action.SHORT: -1, Action.NO_TRADE: 0}
