"""Forward (live, paper) evaluation of the three event-driven strategies S4 / S5 / S6.

``arven paper strategies`` is the composition root: REST-update market data, then for every 15m close since the last
processed one ask each strategy's provider (the same objects the backtest uses - one code path) whether it would
signal, persist new signals to the signal store (``<data_dir>/signals/<strategy_id>/signals.jsonl``), resolve every stored
signal on 1m bars with the Phase 4 ``track_signal`` under the **broker (CFD) cost profile**, append the resulting updates,
and write a summary that also tracks the owner's "agreement" hypothesis (a signal confirmed by another strategy on the same
side within 4 h vs a lone signal; see docs/signal_patterns.md section 4). Nothing here places orders (CLAUDE.md rule 12).

Forward paper signals are *independent* (every signal is resolved on its own as if the account were flat): that matches the
per-signal outcome used in the ML/pattern studies, and unlike the legacy backtest rendering it uses the full 3-rung ladder
(50/30/20) of ``EngineSignal`` - so forward numbers are comparable to the studies' ladder-free V0 only roughly.

Idempotent and restart-safe: the persisted cursor is the last processed 15m close per strategy; a signal is never written
twice; updates are appended only if not already stored.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from arven.backtest.costs import adverse_price, slippage_fraction, taker_fee_rate
from arven.backtest.marketdata import MarketData, align_funding
from arven.backtest.paper_tracker import track_signal
from arven.backtest.provider import DecisionContext, PortfolioSnapshot, SignalProvider
from arven.backtest.strategy_s4_provider import ImpulseRetestProvider
from arven.backtest.strategy_s5_provider import SqueezeBreakoutProvider
from arven.backtest.strategy_s6_provider import TrendPullbackProvider
from arven.core.config import AppConfig, CostsConfig
from arven.core.features_config import FeaturesConfig
from arven.core.splitguard import BacktestPeriod, SplitViolation
from arven.core.time import to_ms, utc_now
from arven.core.timeframes import Timeframe
from arven.data.reader import load_1m_bars, load_feature_inputs, load_funding_window, open_readonly
from arven.data.rest_ingestion import RestTailSummary
from arven.data.storage.db import connect, git_commit
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate
from arven.engine.signal_store import append_signal, append_update, read_signals, read_updates
from arven.paper.runs import latest_forward_window_end_ms, paper_dir, update_market_data
from arven.runs import make_guard

MIN15 = Timeframe.M15.ms
HOUR_MS = 3_600_000
AGREEMENT_WINDOW_MS = 4 * HOUR_MS
ALERT_RECENCY_MS = 6 * HOUR_MS  # catch-up signals older than this are stored but never sent to Telegram

PROVIDERS: dict[str, Callable[..., SignalProvider]] = {
    "s4_impulse_retest": ImpulseRetestProvider,
    "s5_squeeze_breakout": SqueezeBreakoutProvider,
    "s6_trend_pullback": TrendPullbackProvider,
}


def load_cfd_costs(config_dir: Path) -> CostsConfig:
    return CostsConfig.model_validate(yaml.safe_load((config_dir / "costs_cfd_justmarkets.yaml").read_text(encoding="utf-8")))


def event_times(cursor_ms: int, last_close_ms: int) -> range:
    """15m close times strictly after ``cursor_ms`` up to and including ``last_close_ms``."""
    first = (cursor_ms // MIN15 + 1) * MIN15
    return range(first, last_close_ms + 1, MIN15)


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


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


@dataclass(frozen=True, slots=True)
class StrategiesTickOutcome:
    rest_summary: RestTailSummary
    window_end_ms: int | None
    new_signals: dict[str, int]
    summary: dict[str, Any] | None


def run_strategies_tick(
    app: AppConfig, fcfg: FeaturesConfig, config_dir: Path, *, now=None, downloader=None, chat_ids: frozenset[str] = frozenset(),
    on_progress: Callable[[str, int, int], None] | None = None,
) -> StrategiesTickOutcome:
    from arven.telegram.messages import format_new_signal
    from arven.telegram.outbox import enqueue

    now = now or utc_now()
    costs = load_cfd_costs(config_dir)
    signals_root = app.data.data_dir / "signals"
    root = paper_dir(app)
    root.mkdir(parents=True, exist_ok=True)
    cursor_path, summary_path = root / "strategies_cursor.json", root / "strategies_summary.json"
    end_ms = latest_forward_window_end_ms(app, now)
    with connect(app.data.database_path) as con:
        rest = update_market_data(app, con, end_ms, downloader, now)
    try:
        window = make_guard(app).resolve(BacktestPeriod.FORWARD, end_ms=end_ms)
    except SplitViolation:
        return StrategiesTickOutcome(rest, None, {}, None)

    con = open_readonly(app.data.database_path)
    try:
        bars = load_feature_inputs(con, app, end=now).bars
        ranges: list[dict[str, Any]] = []
        m1 = load_1m_bars(con, app.market.symbol, window, ranges)
        f_t, f_r = load_funding_window(con, app.market.symbol, window, ranges)
    finally:
        con.close()
    interval_ms = app.costs.funding.default_interval_hours * HOUR_MS
    ft, fr = align_funding(f_t, f_r, window.start_ms, window.end_ms, interval_ms)
    market = MarketData(m1["time_ms"], m1["open"], m1["high"], m1["low"], m1["close"], window.start_ms, window.end_ms, ft, fr, interval_ms)

    cursors: dict[str, int] = _read_json(cursor_path, {})
    m15 = bars[Timeframe.M15]
    last_close_ms = int(m15.open_time_ms[-1]) + MIN15
    config_hash, commit = fcfg.config_hash(), git_commit()
    new_counts: dict[str, int] = {}
    now_ms = to_ms(now)
    for sid, factory in PROVIDERS.items():
        provider = factory(bars[Timeframe.H1], m15, bars[Timeframe.H4])
        stored = read_signals(signals_root, sid)
        if stored and hasattr(provider, "_last_signal_ms"):
            provider._last_signal_ms = max(s.event_time_ms for s in stored)  # type: ignore[attr-defined]
        times = event_times(cursors.get(sid, window.start_ms - 1), last_close_ms)
        known = {s.signal_id for s in stored}
        fresh = [
            s for s in process_events(
                provider, times, feature_version=fcfg.version, config_hash=config_hash, commit=commit,
                on_progress=(lambda d, n, sid=sid: on_progress(sid, d, n)) if on_progress else None,
            ) if s.signal_id not in known
        ]
        for s in fresh:
            append_signal(signals_root, s)
            if chat_ids and now_ms - s.event_time_ms <= ALERT_RECENCY_MS:
                with connect(app.data.database_path) as con2:
                    for chat in sorted(chat_ids):
                        enqueue(con2, signal_id=s.signal_id, event_type="new_signal", chat_id=chat, text=format_new_signal(s), now_ms=now_ms)
        new_counts[sid] = len(fresh)
        if len(times):
            cursors[sid] = times[-1]
    cursor_path.write_text(json.dumps(cursors, sort_keys=True), encoding="utf-8")

    outcomes_by_strategy: dict[str, list[SignalOutcome]] = {}
    for sid in PROVIDERS:
        have = {(u.signal_id, u.time_ms, u.kind.value, u.detail) for u in read_updates(signals_root, sid)}
        outs: list[SignalOutcome] = []
        for s in read_signals(signals_root, sid):
            out = resolve_signal(s, market, costs)
            if out is None:
                continue
            for u in out.updates:
                if (u.signal_id, u.time_ms, u.kind.value, u.detail) not in have:
                    append_update(signals_root, sid, u)
            outs.append(out)
        outcomes_by_strategy[sid] = outs
    weeks = max((last_close_ms - window.start_ms) / (7 * 86_400_000), 1e-9)
    all_outcomes = [o for v in outcomes_by_strategy.values() for o in v]
    summary = {
        "generated_at": now.isoformat(), "forward_start_ms": window.start_ms, "data_through_ms": last_close_ms,
        "cost_profile": "config/costs_cfd_justmarkets.yaml (broker CFD, spread only)", "git_commit": commit,
        "strategies": {sid: strategy_summary(v, weeks) for sid, v in outcomes_by_strategy.items()},
        "agreement_hypothesis": agreement_summary(all_outcomes),
        "trades": trade_log(outcomes_by_strategy),
        "note": "paper results on live data, full 50/30/20 ladder, signals resolved independently; not evidence of profitability",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return StrategiesTickOutcome(rest, window.end_ms, new_counts, summary)


__all__ = ["PROVIDERS", "SignalOutcome", "StrategiesTickOutcome", "agreement_summary", "event_times", "process_events", "resolve_signal", "run_strategies_tick", "strategy_summary", "trade_log"]
