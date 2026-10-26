"""One tick of the live signal loop (the composition root - all database / network / file I/O lives here).

1. REST-update the market data (1m klines, funding and - for Crowded Shorts - open interest), resample.
2. Decide how far the data is complete: ``through_ms`` = the last 15m close whose 1m bars are all stored (and at least
   ``event_delay_seconds`` old). If the newest 1m bar is older than ``max_data_age_seconds`` the data is **stale**: the
   tick stops here - no strategy is asked for anything (CLAUDE.md rule 5: stale data => NO_TRADE), cursors stay put,
   and the next fresh tick catches up (catch-up signals are stored, but alerted only if recent).
3. Every enabled strategy (``config/live.yaml``) scans the decision times since its own cursor; new signals are
   appended to the signal store (``<data_dir>/signals/<strategy_id>/``), never twice.
4. Every stored signal is replayed on the 1m data (fill, TP hits, stop moves, cancellation, close) and its new updates
   are appended; recent new signals and updates are queued for Telegram (the outbox de-duplicates).
5. A summary for the web app / bot (``<data_dir>/paper/strategies_summary.json``).

Idempotent and restart-safe: cursors are persisted per strategy (``<data_dir>/paper/strategies_cursor.json``, the
same file the forward evaluation of S4-S6 has always used, so their history continues); a strategy whose scan fails
keeps its cursor and is retried next tick, the others carry on. Nothing here places an order (CLAUDE.md rule 12).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from arven.backtest.marketdata import MarketData, funding_schedule
from arven.core.config import AppConfig, CostsConfig
from arven.core.features_config import FeaturesConfig
from arven.core.live_config import LiveConfig
from arven.core.splitguard import BacktestPeriod, SplitViolation
from arven.core.time import to_ms, utc_now
from arven.core.timeframes import Timeframe
from arven.data.reader import EXTRA_TIMEFRAMES, load_1m_bars, load_bar_map, load_feature_inputs, load_funding_window, open_readonly
from arven.data.rest_ingestion import RestTailSummary
from arven.data.storage.db import connect, git_commit
from arven.engine.signal import EngineSignal
from arven.engine.signal_store import append_signal, append_update, read_signals, read_updates
from arven.live.base import LiveContext, LiveOutcome, LiveStrategy
from arven.live.conflicts import ActiveSignal, check, end_of, priority
from arven.live.registry import build_strategies, needs_features
from arven.live.review import forward_review
from arven.live.strategies import natural_key
from arven.paper.runs import latest_forward_window_end_ms, load_paper_inputs, paper_dir, update_market_data
from arven.paper.strategies_forward import SignalOutcome, agreement_summary, trade_log
from arven.runs import make_guard
from arven.telegram.messages import TrackRecord

MIN15 = Timeframe.M15.ms
MIN1 = Timeframe.M1.ms
HOUR_MS = 3_600_000
WEEK_MS = 7 * 86_400_000


def load_costs(config_dir: Path, name: str) -> CostsConfig:
    return CostsConfig.model_validate(yaml.safe_load((config_dir / name).read_text(encoding="utf-8")))


def complete_through_ms(last_1m_open_ms: int | None, now_ms: int, event_delay_ms: int) -> int | None:
    """The last 15m close covered by stored 1m data and at least ``event_delay_ms`` in the past (None: no data)."""
    if last_1m_open_ms is None:
        return None
    by_data = (last_1m_open_ms + MIN1) // MIN15 * MIN15
    by_clock = (now_ms - event_delay_ms) // MIN15 * MIN15
    return min(by_data, by_clock)


@dataclass
class StrategyTick:
    new_signals: list[EngineSignal] = field(default_factory=list)
    new_updates: int = 0
    outcomes: list[LiveOutcome] = field(default_factory=list)
    error: str | None = None


@dataclass
class LiveTickOutcome:
    status: str  # "ok" | "stale" | "not_started" | "no_data" | "error"
    rest: RestTailSummary | None
    through_ms: int | None = None
    last_1m_ms: int | None = None
    strategies: dict[str, StrategyTick] = field(default_factory=dict)
    queued_alerts: int = 0
    summary: dict[str, Any] | None = None
    detail: str = ""
    charts: int = 0  # alert pictures drawn (docs/FEATURES_PLAN.md H5)
    chart_errors: list[str] = field(default_factory=list)  # a picture that could not be drawn: that alert goes as text

    @property
    def errors(self) -> list[str]:
        out = list(self.rest.errors) if self.rest else []
        out += [f"{sid}: {st.error}" for sid, st in self.strategies.items() if st.error]
        return out


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _update_event_type(u: Any) -> str:
    digest = hashlib.sha256(f"{u.time_ms}|{u.kind.value}|{u.detail}".encode()).hexdigest()[:16]
    return f"update:{u.kind.value}:{digest}"


def track_record(outcomes: Sequence[LiveOutcome], since_ms: int, exclude_signal_id: str | None = None) -> TrackRecord:
    """The strategy's closed paper signals for a new-signal alert (the alerted signal itself excluded)."""
    rs = [float(o.net_r) for o in outcomes
          if o.state == "closed" and o.net_r is not None and o.signal.signal_id != exclude_signal_id]
    return TrackRecord(len(rs), sum(1 for r in rs if r > 0), float(sum(rs)), since_ms)


def summarize(outcomes: Sequence[LiveOutcome], weeks: float, min_closed: int = 30) -> dict[str, Any]:
    done = sorted((o for o in outcomes if o.state == "closed" and o.net_r is not None),
                  key=lambda o: max((u.time_ms for u in o.updates), default=0))  # closing-time order for the drawdown
    closed = [float(o.net_r) for o in done]  # type: ignore[arg-type]
    states = [o.state for o in outcomes]
    return {
        "signals": len(outcomes), "closed": len(closed), "open": states.count("open"), "pending": states.count("pending"),
        "cancelled": states.count("cancelled"), "signals_per_week": len(outcomes) / weeks if weeks > 0 else None,
        "total_r": float(np.sum(closed)) if closed else 0.0, "mean_r": float(np.mean(closed)) if closed else None,
        "win_rate": float(np.mean(np.array(closed) > 0)) if closed else None,
        "review": forward_review(closed, min_closed),
    }


def run_live_tick(
    app: AppConfig, fcfg: FeaturesConfig, live: LiveConfig, config_dir: Path, *, now: datetime | None = None, downloader=None,
    chat_ids: frozenset[str] = frozenset(), strategies: list[LiveStrategy] | None = None, telegram_enqueue=None,
) -> LiveTickOutcome:
    """One tick (see the module docstring). ``telegram_enqueue(con, signal_id, event_type, chat_id, text, now_ms)``
    is injectable for tests; by default the real outbox."""
    from arven.telegram.chart import candles_until, chart_language, render_signal_chart
    from arven.telegram.messages import chart_title, format_conflict_note, format_new_signal, format_signal_update, update_label
    from arven.telegram.outbox import charts_dir, enqueue, save_chart

    now = now or utc_now()
    now_ms = to_ms(now)
    strategies = strategies if strategies is not None else build_strategies(live)
    costs = load_costs(config_dir, live.cost_profile)
    signals_root = app.market_root / "signals"
    root = paper_dir(app)
    root.mkdir(parents=True, exist_ok=True)
    cursor_path, summary_path = root / "strategies_cursor.json", root / "strategies_summary.json"

    end_ms = latest_forward_window_end_ms(app, now)
    with connect(app.data.database_path) as con:
        rest = update_market_data(app, con, end_ms, downloader, now, include_open_interest=live.include_open_interest)
    try:
        window = make_guard(app).resolve(BacktestPeriod.FORWARD, end_ms=end_ms)
    except SplitViolation:
        return LiveTickOutcome("not_started", rest, detail="forward_start has not arrived yet")

    con = open_readonly(app.data.database_path)
    try:
        bars = {**load_feature_inputs(con, app, end=now).bars, **load_bar_map(con, app, EXTRA_TIMEFRAMES, end=now)}
        ranges: list[dict[str, Any]] = []
        m1 = load_1m_bars(con, app.market.symbol, window, ranges)
        f_t, f_r = load_funding_window(con, app.market.symbol, window, ranges)
    finally:
        con.close()
    if len(m1["time_ms"]) == 0:
        return LiveTickOutcome("no_data", rest, detail="no 1m bars in the forward window")
    ft, fr, interval_ms = funding_schedule(app.costs.funding, f_t, f_r, window.start_ms, window.end_ms)
    market = MarketData(m1["time_ms"], m1["open"], m1["high"], m1["low"], m1["close"], window.start_ms, window.end_ms, ft, fr, interval_ms,
                        calendar=app.session_calendar())

    last_1m = int(m1["time_ms"][-1])
    calendar = app.session_calendar()
    through = complete_through_ms(last_1m, now_ms, live.event_delay_seconds * 1000)
    m15 = bars[Timeframe.M15]
    through = min(through, int(m15.open_time_ms[-1]) + MIN15) if len(m15) else through
    if not calendar.always_open and not len(calendar.open_minutes(last_1m + MIN1, now_ms - live.event_delay_seconds * 1000)):
        # a session market whose every open minute up to now is stored (it is closed): complete through the clock, so
        # the loop does not re-run the tick every poll of a weekend (nothing actionable can happen while closed)
        through = max(through, complete_through_ms(now_ms, now_ms, live.event_delay_seconds * 1000) or through)
    # data age in *trading* time (= wall time around the clock): a session market's data is not stale while it is closed
    lag_ms = int(calendar.trading_ms(now_ms)) - int(calendar.trading_ms(last_1m + MIN1))
    stale = lag_ms > live.max_data_age_seconds * 1000
    features_loader = (lambda: load_paper_inputs(app, fcfg, window).features) if needs_features(live) else None
    ctx = LiveContext(app, fcfg, costs, window, bars, market, through, fcfg.version, fcfg.config_hash(), git_commit(), features_loader)
    closed = not calendar.always_open and not calendar.is_open(now_ms // MIN1 * MIN1)
    outcome = LiveTickOutcome("stale" if stale else "ok", rest, through, last_1m,
                              detail=f"newest 1m bar is {lag_ms / 1000:.0f}s old" if stale else ("market closed" if closed else ""))
    if stale:
        return outcome

    cursors: dict[str, int] = _read_json(cursor_path, {})
    alerts: list[tuple[str, str, str]] = []  # (signal_id, event_type, text)
    charts_on = live.telegram.enabled and live.telegram.charts and bool(chat_ids)
    lang = live.telegram.language
    chart_lang = chart_language(lang)  # the picture's words: Russian only with a Cyrillic font installed

    def picture(strat: LiveStrategy, s: EngineSignal, event_type: str, u: Any = None) -> None:
        """The alert's picture, from the 15m candles closed by the signal (or the update) - never later ones - with
        the strategy's own drawing if it has one (S7: trend line, fib levels, entry zone)."""
        if not charts_on:
            return
        try:
            cut = s.event_time_ms if u is None else u.time_ms
            draw = getattr(strat, "overlay", None)
            ov = draw(ctx, s) if draw is not None else None
            c = candles_until(m15.open_time_ms, Timeframe.M15.ms, m15.open, m15.high, m15.low, m15.close, cut, "15m",
                              since_ms=None if ov is None else ov.start_ms)
            png = render_signal_chart(s, c, chart_title(s, u, chart_lang), update=u,
                                      update_label=None if u is None else update_label(u, chart_lang), overlay=ov, lang=chart_lang)
            save_chart(charts_dir(app.data.data_dir), s.signal_id, event_type, png)
            outcome.charts += 1
        except Exception as exc:  # noqa: BLE001 - the picture is optional; the alert still goes out as text
            outcome.chart_errors.append(f"{s.signal_id} {event_type}: {type(exc).__name__}: {exc}")
    recency_ms = int(live.alert_recency_hours * HOUR_MS)
    later: list[tuple[LiveStrategy, StrategyTick, list[EngineSignal], list[tuple[str, str, str]]]] = []  # alerts, in strategy order
    for strat in strategies:
        sid = strat.strategy_id
        st = outcome.strategies[sid] = StrategyTick()
        try:
            stored = read_signals(signals_root, sid)
            after = cursors.get(sid, window.start_ms - 1)
            known = {natural_key(s) for s in stored}
            fresh: list[EngineSignal] = []  # new signals to alert, formatted below once the record is known
            for s in strat.scan(ctx, after, through, stored):
                if natural_key(s) in known:
                    continue
                known.add(natural_key(s))
                append_signal(signals_root, s)
                st.new_signals.append(s)
                if now_ms - s.event_time_ms <= recency_ms:
                    fresh.append(s)
            cursors[sid] = max(after, through)
            have = {(u.signal_id, u.time_ms, u.kind.value, u.detail) for u in read_updates(signals_root, sid)}
            update_alerts: list[tuple[str, str, str]] = []
            for s in [*stored, *st.new_signals]:
                res = strat.resolve(ctx, s)
                if res is None:
                    continue
                st.outcomes.append(res)
                for u in res.updates:
                    if (u.signal_id, u.time_ms, u.kind.value, u.detail) in have:
                        continue
                    append_update(signals_root, sid, u)
                    st.new_updates += 1
                    if live.telegram.send_updates and now_ms - u.time_ms <= recency_ms:
                        picture(strat, s, _update_event_type(u), u)
                        update_alerts.append((s.signal_id, _update_event_type(u), format_signal_update(s, u, lang)))
            later.append((strat, st, fresh, update_alerts))
        except Exception as exc:  # noqa: BLE001 - one strategy's failure must not stop the others
            st.error = f"{type(exc).__name__}: {exc}"
    cursor_path.write_text(json.dumps(cursors, sort_keys=True), encoding="utf-8")

    # every strategy is resolved now: a new signal can be checked against the others' active signals (arven.live.conflicts)
    order = {s.strategy_id: k for k, s in enumerate(strategies)}
    active = [ActiveSignal(o.signal.signal_id, sid, getattr(s, "title", sid), getattr(s, "tf", "15m"), o.signal.side, o.signal.event_time_ms,
                           end_of(o.updates), priority(getattr(s, "tf", "15m"), order[sid]))
              for s in strategies for sid in [s.strategy_id] for o in outcome.strategies[sid].outcomes] if live.conflict_mode != "off" else []
    for strat, st, fresh, update_alerts in later:
        for s in fresh:  # same order as before: the strategy's new signals, then its updates
            picture(strat, s, "new_signal")
            text = format_new_signal(s, track_record(st.outcomes, window.start_ms, s.signal_id), lang)
            if live.conflict_mode != "off":
                me = ActiveSignal(s.signal_id, strat.strategy_id, getattr(strat, "title", strat.strategy_id), getattr(strat, "tf", "15m"), s.side,
                                  s.event_time_ms, None, priority(getattr(strat, "tf", "15m"), order[strat.strategy_id]))
                opposite, same = check(me, active)
                note = format_conflict_note(opposite, same, live.conflict_mode, lang)
                if note:
                    text = f"{note}\n\n{text}"
                if opposite or same:
                    with (root / "conflicts.jsonl").open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"signal_id": s.signal_id, "strategy": strat.strategy_id, "side": s.side, "time_ms": s.event_time_ms,
                                             "mode": live.conflict_mode, "against": [o.signal_id for o in opposite], "confirms": [o.signal_id for o in same]},
                                            sort_keys=True) + "\n")
            alerts.append((s.signal_id, "new_signal", text))
        alerts.extend(update_alerts)

    if live.telegram.enabled and chat_ids and alerts:
        put = telegram_enqueue or (lambda c, signal_id, event_type, chat_id, text, now_ms: enqueue(
            c, signal_id=signal_id, event_type=event_type, chat_id=chat_id, text=text, now_ms=now_ms))
        with connect(app.data.database_path) as con2:
            for signal_id, event_type, text in alerts:
                for chat in sorted(chat_ids):
                    put(con2, signal_id, event_type, chat, text, now_ms)
                    outcome.queued_alerts += 1

    weeks = max((through - window.start_ms) / WEEK_MS, 1e-9)
    as_forward = {sid: [SignalOutcome(o.signal, o.state == "closed", o.net_r, o.updates) for o in st.outcomes] for sid, st in outcome.strategies.items()}
    outcome.summary = {
        "generated_at": now.isoformat(), "forward_start_ms": window.start_ms, "data_through_ms": through, "last_1m_ms": last_1m,
        "status": outcome.status, "cost_profile": f"config/{live.cost_profile}", "git_commit": ctx.git_commit,
        "strategies": {sid: summarize(st.outcomes, weeks, live.forward_review.min_closed) | {"title": next((s.title for s in strategies if s.strategy_id == sid), sid), "error": st.error}
                       for sid, st in outcome.strategies.items()},
        "agreement_hypothesis": agreement_summary([o for v in as_forward.values() for o in v]),
        "trades": trade_log(as_forward),
        "closed_signals": sorted(
            ({"signal_id": o.signal.signal_id, "strategy": sid, "closed_ms": max(u.time_ms for u in o.updates), "r": o.net_r}
             for sid, st in outcome.strategies.items() for o in st.outcomes if o.state == "closed" and o.updates),
            key=lambda d: d["closed_ms"]),
        "note": "paper signals on live data, each tracked on its own (as if the account were flat); not evidence of profitability",
    }
    summary_path.write_text(json.dumps(outcome.summary, indent=2, sort_keys=True), encoding="utf-8")
    if outcome.errors and outcome.status == "ok":
        outcome.status = "error"
        outcome.detail = "; ".join(outcome.errors)[:500]
    return outcome


__all__ = ["LiveTickOutcome", "StrategyTick", "complete_through_ms", "load_costs", "run_live_tick", "summarize", "track_record"]
