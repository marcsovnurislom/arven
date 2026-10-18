"""Forward (live, paper) evaluation helpers for the event-driven strategies S4 / S5 / S6.

The composition root is now the live loop (``arven.live.service.run_live_tick``; ``arven paper strategies`` is an
alias of ``arven live tick``); this module keeps the pieces it reuses: ask a provider (the same objects the backtest
uses - one code path) about every 15m close, resolve a stored signal on 1m bars with the Phase 4 ``track_signal``
under the **broker (CFD) cost profile**, and the summaries, including the owner's "agreement" hypothesis (a signal
confirmed by another strategy on the same side within 4 h vs a lone signal; docs/signal_patterns.md section 4).
Nothing here places orders (CLAUDE.md rule 12).

Forward paper signals are *independent* (every signal is resolved on its own as if the account were flat): that matches the
per-signal outcome used in the ML/pattern studies, and unlike the legacy backtest rendering it uses the full 3-rung ladder
(50/30/20) of ``EngineSignal`` - so forward numbers are comparable to the studies' ladder-free V0 only roughly.

Idempotent and restart-safe: the persisted cursor is the last processed 15m close per strategy; a signal is never written
twice; updates are appended only if not already stored.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.marketdata import MarketData
from arven.backtest.paper_tracker import track_signal
from arven.backtest.provider import DecisionContext, PortfolioSnapshot, SignalProvider
from arven.backtest.strategy_s4_provider import ImpulseRetestProvider
from arven.backtest.strategy_s5_provider import SqueezeBreakoutProvider
from arven.backtest.strategy_s6_provider import TrendPullbackProvider
from arven.core.config import CostsConfig
from arven.core.sessions import SessionCalendar, session_decision_mask
from arven.core.timeframes import Timeframe
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate

MIN15 = Timeframe.M15.ms
HOUR_MS = 3_600_000
AGREEMENT_WINDOW_MS = 4 * HOUR_MS

PROVIDERS: dict[str, Callable[..., SignalProvider]] = {
    "s4_impulse_retest": ImpulseRetestProvider,
    "s5_squeeze_breakout": SqueezeBreakoutProvider,
    "s6_trend_pullback": TrendPullbackProvider,
}


def load_cfd_costs(config_dir: Path) -> CostsConfig:
    return CostsConfig.model_validate(yaml.safe_load((config_dir / "costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))


def event_times(cursor_ms: int, last_close_ms: int, calendar: SessionCalendar | None = None) -> Sequence[int]:
    """15m close times strictly after ``cursor_ms`` up to and including ``last_close_ms``; for a session market only
    those a trader could act on (:func:`arven.core.sessions.session_decision_mask`)."""
    first = (cursor_ms // MIN15 + 1) * MIN15
    times = range(first, last_close_ms + 1, MIN15)
    if calendar is None or calendar.always_open:
        return times
    grid = np.arange(first, last_close_ms + 1, MIN15, dtype=np.int64)
    return [int(t) for t in grid[session_decision_mask(calendar, grid, Timeframe.M15)]]


def flat_context(now_ms: int) -> DecisionContext:
    flat = PortfolioSnapshot(equity=10_000.0, wallet=10_000.0, side=0, qty=0.0, entry_price=0.0, unrealized=0.0, available_margin=10_000.0, order_pending=False)
    return DecisionContext(now_ms=now_ms, index=0, features=None, portfolio=flat, period="forward")


def process_events(
    provider: SignalProvider, times: Sequence[int], *, feature_version: str, config_hash: str, commit: str | None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[EngineSignal]:
    """Ask ``provider`` about every event time in order; return the signals it would have published."""
    out: list[EngineSignal] = []
    for i, t in enumerate(times):
        if provider.decide(flat_context(t)) is not None:
            es = provider.to_engine_signal(t, feature_version=feature_version, config_hash=config_hash, git_commit=commit)  # type: ignore[attr-defined]
            if es is not None:
                out.append(es)
        if on_progress and (i + 1) % 1000 == 0:
            on_progress(i + 1, len(times))
    return out


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    signal: EngineSignal
    closed: bool
    net_r: float | None  # None while nothing has resolved; for a partly-closed ladder it is the realised part
    updates: tuple[SignalUpdate, ...]


def resolve_signal(signal: EngineSignal, market: MarketData, costs: CostsConfig) -> SignalOutcome | None:
    """Fill at the 1m bar of the decision time (adverse slippage), then walk the ladder/stop on 1m bars. ``None`` if
    the decision-time bar is not in ``market`` yet (the forward window has not reached it)."""
    t = signal.event_time_ms
    i = market.first_at_or_after(t)
    if i >= len(market) or int(market.time_ms[i]) != t:
        return None
    o, h, lo = float(market.open[i]), float(market.high[i]), float(market.low[i])
    fill = adverse_price(o, signal.side, slippage_fraction(o, h, lo, costs, False))
    result = track_signal(signal, t, fill, market, costs)
    updates = tuple(SignalUpdate(signal.signal_id, u.time_ms, u.kind, u.detail) for u in result.updates)
    if result.resolution is None:
        return SignalOutcome(signal, False, None, updates)
    risk = abs(fill - signal.stop)
    entry_fee = fill * taker_fee_rate(costs)
    return SignalOutcome(signal, result.resolution.fully_closed, result.resolution.r_multiple - entry_fee / risk, updates)


def agreement_summary(outcomes: Sequence[SignalOutcome]) -> dict[str, dict[str, float | int]]:
    """Closed signals split by whether a *different* strategy signalled on the same side within 4 h (any state)."""
    signals = [o.signal for o in outcomes]
    groups: dict[str, list[float]] = {"alone": [], "agreed_by_another_strategy": []}
    for o in outcomes:
        if not o.closed or o.net_r is None:
            continue
        s = o.signal
        agreed = any(
            x.strategy_id != s.strategy_id and x.side == s.side and abs(x.event_time_ms - s.event_time_ms) <= AGREEMENT_WINDOW_MS
            for x in signals
        )
        groups["agreed_by_another_strategy" if agreed else "alone"].append(o.net_r)
    return {
        k: {"n": len(v), "mean_r": float(np.mean(v)) if v else float("nan"), "win_rate": float(np.mean(np.array(v) > 0)) if v else float("nan")}
        for k, v in groups.items()
    }


def strategy_summary(outcomes: Sequence[SignalOutcome], weeks: float) -> dict[str, Any]:
    closed = [o.net_r for o in outcomes if o.closed and o.net_r is not None]
    return {
        "signals": len(outcomes), "closed": len(closed), "open": len(outcomes) - len(closed),
        "signals_per_week": len(outcomes) / weeks if weeks > 0 else None,
        "total_r": float(np.sum(closed)) if closed else 0.0, "mean_r": float(np.mean(closed)) if closed else None,
        "win_rate": float(np.mean(np.array(closed) > 0)) if closed else None,
    }


def trade_log(outcomes_by_strategy: dict[str, Sequence[SignalOutcome]]) -> list[dict[str, Any]]:
    """Closed signals, oldest first - the series behind the web app's equity curve in R (each signal resolved independently)."""
    rows = [
        {"t": o.signal.event_time_ms, "strategy": sid, "side": o.signal.side, "r": o.net_r}
        for sid, outs in outcomes_by_strategy.items() for o in outs if o.closed and o.net_r is not None
    ]
    return sorted(rows, key=lambda r: r["t"])


__all__ = ["PROVIDERS", "SignalOutcome", "agreement_summary", "event_times", "process_events", "resolve_signal", "strategy_summary", "trade_log"]
