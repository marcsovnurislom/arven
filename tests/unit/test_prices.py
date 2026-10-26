"""arven.core.prices: decimals by size, BTC / gold unchanged at 2, one signal written with one precision."""

from arven.core.prices import fmt_price, price_decimals


def test_decimals_follow_the_price_size():
    assert [price_decimals(p) for p in (80_000.0, 4_000.0, 100.0, 25.3, 1.11767, 0.21)] == [2, 2, 2, 3, 5, 5]
    assert fmt_price(80_945.674) == "80945.67" and fmt_price(1.117674) == "1.11767" and fmt_price(0.21234) == "0.21234"


def test_a_reference_sets_the_precision_for_every_level():
    assert fmt_price(98.0, 100.0) == "98.00" and fmt_price(1.0991, 1.1005) == "1.09910"
