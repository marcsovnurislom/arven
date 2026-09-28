"""Isolated-margin arithmetic (pure)."""

from __future__ import annotations

import math


def initial_margin(notional: float, leverage: float) -> float:
    return notional / leverage


def liquidation_price(side: int, entry_price: float, leverage: float, maintenance_rate: float) -> float:
    """Price at which margin balance equals maintenance margin (isolated, one position, margin = notional / L).

    margin + side * q * (P - E) = mmr * q * P  =>
        long : P = E * (1 - 1/L) / (1 - mmr)
        short: P = E * (1 + 1/L) / (1 + mmr)
    Fees and funding are settled against the wallet, not the margin, so the price is fixed at entry.
    """
    if side > 0:
        return entry_price * (1.0 - 1.0 / leverage) / (1.0 - maintenance_rate)
    return entry_price * (1.0 + 1.0 / leverage) / (1.0 + maintenance_rate)


def liquidation_price_from_margin(side: int, entry_price: float, qty: float, margin_balance: float, maintenance_rate: float) -> float:
    """Liquidation price when the isolated margin balance at the entry price is ``margin_balance`` (margin + funding).

    margin_balance + side * q * (P - E) = mmr * q * P  =>
        long : P = (E - margin_balance / q) / (1 - mmr)
        short: P = (E + margin_balance / q) / (1 + mmr)
    With ``margin_balance = q * E / L`` this equals :func:`liquidation_price`.
    """
    if side > 0:
        return (entry_price - margin_balance / qty) / (1.0 - maintenance_rate)
    return (entry_price + margin_balance / qty) / (1.0 + maintenance_rate)


def qty_from_notional(target_notional: float, price: float, step: float) -> float:
    """Largest multiple of ``step`` whose notional at ``price`` does not exceed ``target_notional``."""
    lots = math.floor(target_notional / price / step)
    return max(lots, 0) * step
