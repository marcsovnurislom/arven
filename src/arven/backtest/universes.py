""""1000 parallel universes" (docs/FEATURES_PLAN.md, H3): is a strategy's result skill or luck?

Each universe is a random trader who makes exactly the strategy's trades - the same side, the same stop distance (as a
fraction of the price) and the same take-profit ladder in R - but enters each of them at a random 1m bar of the same
period instead of at the strategy's signal. Every random trade is resolved by the same paper tracker with the same
costs as the strategy (:func:`arven.backtest.paper_tracker.track_signal`), and the trades are replayed on the same
$1000 account (:func:`arven.backtest.account_sim.replay_account`). Where the strategy's final balance falls among the
universes (its percentile) says how unusual it is: below the 95th percentile it is indistinguishable from luck.

This is the per-trade idea of the S7 study's ``random_control`` turned into whole account curves. Seeded and
deterministic; research output only, it never places or changes a signal.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from arven.backtest.account_sim import AccountRules, TradeForAccount, replay_account
from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.marketdata import MarketData
from arven.backtest.paper_tracker import track_signal
from arven.core.config import CostsConfig
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel

LADDER_FRACTIONS: tuple[float, ...] = (0.5, 0.3, 0.2)  # every strategy's TP ladder closes 50 / 30 / 20 %
RESOLVE_HORIZON_MS = 30 * 86_400_000  # random entries keep this much data after them, so most trades can resolve
SKILL_PERCENTILE = 95.0  # the project's random-control bar (the S7 evaluation rule)
MIN_TRADES = 30  # fewer trades than this: no verdict (the forward review rule's minimum)


@dataclass(frozen=True, slots=True)
class TradeTemplate:
    """What a random trader copies from one strategy trade: side, stop distance and the ladder in R."""

    side: int
    stop_fraction: float  # |entry - stop| / entry
    ladder_r: tuple[float, ...]

    @staticmethod
    def from_trade(side: int, entry: float, stop: float, targets: Sequence[float]) -> TradeTemplate | None:
        """``None`` for a trade without a valid stop or targets (e.g. a time exit): it cannot be copied."""
        risk = abs(entry - stop)
        if risk <= 0 or entry <= 0 or (entry - stop) * side <= 0:
            return None
        ladder = tuple((p - entry) * side / risk for p in targets[: len(LADDER_FRACTIONS)])
        if not ladder or any(r <= 0 for r in ladder):
            return None
        return TradeTemplate(side, risk / entry, ladder)


@dataclass(frozen=True, slots=True)
class RandomTrade:
    entry_time_ms: int
    risk_per_unit: float
    net_r: float


def random_trade(t: TradeTemplate, market: MarketData, i: int, costs: CostsConfig, symbol: str) -> RandomTrade | None:
    """``t`` entered at the open of 1m bar ``i`` (with the strategy's slippage and taker fee); ``None`` while unresolved."""
    o, h, lo = float(market.open[i]), float(market.high[i]), float(market.low[i])
    fill = adverse_price(o, t.side, slippage_fraction(o, h, lo, costs, False))
    stop = fill * (1.0 - t.side * t.stop_fraction)
    fractions = LADDER_FRACTIONS[: len(t.ladder_r)]
    total = sum(fractions)
    ladder = tuple(TPLevel.from_r_multiple(r, f / total, entry=fill, stop=stop, side=t.side) for r, f in zip(t.ladder_r, fractions, strict=True))
    when = int(market.time_ms[i])
    sig = EngineSignal(symbol=symbol, side=t.side, strategy_id="universe", strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=when,
                       entry_reference=fill, stop=stop, tp_ladder=ladder, risk_fraction=0.01, confidence=0.5, regime="universe",
                       reasons=("random entry",), risk_checks=(), versions=SignalVersions("v1", "universe", None))
    res = track_signal(sig, when, fill, market, costs).resolution
    if res is None or not res.fully_closed:
        return None
    risk = abs(fill - stop)
    return RandomTrade(when, risk, res.r_multiple - fill * taker_fee_rate(costs) / risk)


def universe(templates: Sequence[TradeTemplate], market: MarketData, rng: np.random.Generator, costs: CostsConfig, symbol: str,
             horizon_ms: int = RESOLVE_HORIZON_MS) -> list[RandomTrade]:
    """One random trader: every template at a random bar that leaves ``horizon_ms`` of data after it (the whole
    period when it is shorter than that), in time order. Unresolved trades are dropped."""
    n = len(market)
    last = int(np.searchsorted(market.time_ms, int(market.time_ms[-1]) - horizon_ms)) if n else 0
    hi = last if last > n // 4 else n  # a short period (forward): any bar
    out = [x for x in (random_trade(tp, market, int(rng.integers(0, hi)), costs, symbol) for tp in templates) if x is not None]
    return sorted(out, key=lambda x: x.entry_time_ms)


def equity_curve(trades: Sequence[RandomTrade], rules: AccountRules) -> list[float]:
    """The account balance before the first trade and after each one."""
    steps = replay_account([TradeForAccount(x.risk_per_unit, x.net_r) for x in trades], rules)
    return [rules.start_equity, *(s.equity_after for s in steps)]


def thin(curve: Sequence[float], points: int) -> list[float]:
    """At most ``points`` values, evenly spread over the curve, always keeping the first and the last."""
    if len(curve) <= points:
        return list(curve)
    idx = np.unique(np.round(np.linspace(0, len(curve) - 1, points)).astype(int))
    return [curve[i] for i in idx]


def percentile_of(value: float, sample: Sequence[float]) -> float:
    """Share of ``sample`` below ``value`` (ties count half), in percent."""
    a = np.asarray(sample, dtype=float)
    if len(a) == 0:
        return float("nan")
    return float((np.sum(a < value) + 0.5 * np.sum(a == value)) / len(a) * 100.0)


def verdict(percentile: float, trades: int) -> str:
    """``too_few`` under ``MIN_TRADES`` trades (any percentile is noise there), ``skill_candidate`` at or above the 95th
    percentile of the random traders, else ``luck``."""
    if trades < MIN_TRADES:
        return "too_few"
    return "skill_candidate" if percentile >= SKILL_PERCENTILE else "luck"


__all__ = ["LADDER_FRACTIONS", "MIN_TRADES", "SKILL_PERCENTILE", "RandomTrade", "TradeTemplate", "equity_curve", "percentile_of", "random_trade",
           "thin", "universe", "verdict"]
