"""The strategy status grade (`docs/ARVEN_MASTER_PROMPT.md` section 1.3's "signal grading gate").

Every strategy is shown everywhere (Telegram, web, API - later phases) with one of three statuses, computed
by a pure function of its own accumulated track record - never set by hand, never implied by marketing
copy. This module only computes the grade from numbers a caller assembles (:class:`TrackRecord`); it does
not read walk-forward reports, paper-run metrics, or any other artifact itself - wiring a real strategy's
real Stage 7/8 history into a ``TrackRecord`` is later-phase integration work, deliberately out of scope here
(CLAUDE.md rule 6: never claim or imply guaranteed profitability - this module exists specifically so no UI
text ever has to guess).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class Grade(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"  # default: no validated edge; signals are paper / not validated
    VALIDATED = "VALIDATED"  # every criterion in docs/ARVEN_MASTER_PROMPT.md section 1.3 holds
    SUSPENDED = "SUSPENDED"  # forward performance degraded past a pre-registered threshold


# Thresholds pre-registered in docs/ARVEN_MASTER_PROMPT.md section 1.3 (never fitted to make a strategy pass).
MIN_SIMULATED_TRADES = 100
MIN_FORWARD_TRADES = 30
SUSPEND_ROLLING_EXPECTANCY_R = -0.3
SUSPEND_DRAWDOWN_R = 8.0


@dataclass(frozen=True, slots=True)
class TrackRecord:
    """Everything the gate needs about one strategy, already computed elsewhere (Stage 7 walk-forward,
    Stage 4 baselines/stress runs, the forward paper tracker - this dataclass takes no position on how)."""

    wfo_window_total_returns: tuple[float, ...]  # one net total_return per purged walk-forward window
    n_simulated_trades: int  # trades across the walk-forward windows (or the development backtest)
    beats_no_trade: bool
    beats_buy_and_hold: bool
    beats_random_entry: bool
    survives_cost_stress: bool  # net expectancy stays positive at 2x slippage (CLAUDE.md rule 4)
    n_forward_trades: int  # real paper-tracked trades since going live
    forward_net_expectancy_r: float  # mean net R-multiple of those forward trades
    rolling_30_trade_expectancy_r: float | None = None  # None: fewer than 30 forward trades exist yet
    max_drawdown_r: float | None = None  # peak-to-trough drawdown of the forward R-equity curve

    def __post_init__(self) -> None:
        if self.n_simulated_trades < 0 or self.n_forward_trades < 0:
            raise ValueError("trade counts must not be negative")
        if not math.isfinite(self.forward_net_expectancy_r):
            raise ValueError("forward_net_expectancy_r must be finite")
        for r in self.wfo_window_total_returns:
            if not math.isfinite(r):
                raise ValueError("wfo_window_total_returns must all be finite")


def _majority_positive(returns: tuple[float, ...]) -> bool:
    return bool(returns) and sum(r > 0 for r in returns) > len(returns) / 2


def is_suspended(tr: TrackRecord) -> bool:
    """Automatic, independent of whether the strategy ever reached VALIDATED - a strategy that degrades
    while still EXPERIMENTAL is just never promoted, but one that degrades after being VALIDATED must stop
    being shown as such."""
    if tr.rolling_30_trade_expectancy_r is not None and tr.rolling_30_trade_expectancy_r < SUSPEND_ROLLING_EXPECTANCY_R:
        return True
    if tr.max_drawdown_r is not None and tr.max_drawdown_r > SUSPEND_DRAWDOWN_R:
        return True
    return False


def is_validated(tr: TrackRecord) -> bool:
    """All six criteria of section 1.3 - every one, not a majority."""
    return (
        _majority_positive(tr.wfo_window_total_returns)
        and tr.n_simulated_trades >= MIN_SIMULATED_TRADES
        and tr.beats_no_trade
        and tr.beats_buy_and_hold
        and tr.beats_random_entry
        and tr.survives_cost_stress
        and tr.n_forward_trades >= MIN_FORWARD_TRADES
        and tr.forward_net_expectancy_r >= 0.0
    )


def grade(tr: TrackRecord) -> Grade:
    """SUSPENDED takes priority over VALIDATED: a strategy that once qualified but has since degraded is
    shown as suspended, never as still-validated (CLAUDE.md rule 6 - the owner must never be able to
    mistake a degraded strategy for a currently-trustworthy one)."""
    if is_suspended(tr):
        return Grade.SUSPENDED
    if is_validated(tr):
        return Grade.VALIDATED
    return Grade.EXPERIMENTAL
