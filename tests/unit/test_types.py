from arven.core.types import Action


def test_action_values_are_the_three_allowed_outputs():
    assert {a.value for a in Action} == {"LONG", "SHORT", "NO_TRADE"}


def test_action_direction():
    assert Action.LONG.direction == 1
    assert Action.SHORT.direction == -1
    assert Action.NO_TRADE.direction == 0


def test_action_from_direction_roundtrip():
    for action in Action:
        assert Action.from_direction(action.direction) is action
    assert Action.from_direction(0) is Action.NO_TRADE
