"""How a price is written for people (alerts, charts, signal reasons): enough decimals for the instrument's size.

BTC / gold / ETH (>= 100): 2 decimals, exactly as before 2026-10-27; 10-100 (LINK, silver): 3; below 10 (XRP, ADA, DOGE,
EUR/USD, GBP/USD): 5 - a pip on EUR/USD is the 4th decimal, a DOGE tick the 5th.
"""

from __future__ import annotations


def price_decimals(price: float) -> int:
    p = abs(float(price))
    return 2 if p >= 100 else 3 if p >= 10 else 5


def fmt_price(price: float, ref: float | None = None) -> str:
    """``ref``: the price that sets the decimals (a signal's entry), so every level of one signal is written alike."""
    return f"{float(price):.{price_decimals(price if ref is None else ref)}f}"


__all__ = ["fmt_price", "price_decimals"]
