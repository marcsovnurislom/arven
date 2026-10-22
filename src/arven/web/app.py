"""The ARVEN HTTP API (docs/ARVEN_MASTER_PROMPT.md section 5.6): read-only over stored artifacts and market data, plus the
separate manual journal. Binds to 127.0.0.1 by default (``arven web``), CORS is limited to localhost origins, and there is no
endpoint that writes market data or places an order (CLAUDE.md rule 12). Missing data is reported honestly (empty lists /
``null``), never replaced by invented values."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from arven.core.config import AppConfig, load_config
from arven.core.live_config import load_live_config
from arven.core.telegram_config import allowed_chat_ids, load_telegram_config
from arven.core.time import to_ms, utc_now
from arven.web import journal as jr
from arven.web import service as svc
from arven.web import sessions as ses

HEARTBEAT_MAX_AGE_MS = 5 * 60_000  # a live tick can take a couple of minutes; longer than this without a check-in = stale
DATA_STALE_MS = 3 * 3_600_000
ACTIVITY_CACHE_MS = 3_600_000


@dataclass(frozen=True)
class WebMarket:
    """One market the web app shows: ``btc`` (the default configuration) or one of ``config/live.yaml`` ``markets``."""

    id: str
    label: str
    symbol: str  # the live feed's stored symbol (candles, last bar)
    history_symbol: str | None  # stored research history the charts continue into (gold: Dukascopy XAUUSD)
    live_root: Path  # signals/ and paper/ of the live record
    research_root: Path  # strategy_trades/, s7_study/, backtests/ of the research exports
    calendar: Any  # arven.core.sessions.SessionCalendar
    enabled: bool = True
    holidays: tuple[tuple[int, int, str], ...] = ()  # the calendar's holiday / early-close windows with their names

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "symbol": self.symbol, "history_symbol": self.history_symbol,
                "session": self.calendar.kind, "enabled": self.enabled}


def web_markets(cfg: AppConfig, config_dir: Path | str | None) -> dict[str, WebMarket]:
    """``btc`` plus every market of ``config/live.yaml`` (also a disabled one: its research can already be shown)."""
    out = {"btc": WebMarket("btc", "BTC/USDT", cfg.market.symbol, None, cfg.data.data_dir, cfg.data.data_dir, cfg.session_calendar())}
    try:
        markets = load_live_config(config_dir).markets
    except FileNotFoundError:
        markets = ()
    root = cfg.data.data_dir / "markets"  # the same layout as AppConfig.market_root, under *this* app's data directory
    for m in markets:
        live_app = load_config(config_dir, instrument=m.instrument)
        hist = m.history_instrument
        mid = (m.title or m.instrument).lower().replace(" ", "_")
        holidays = tuple((to_ms(c.start), to_ms(c.end), c.reason) for c in live_app.market.session_closures)
        out[mid] = WebMarket(mid, f"{m.title} ({hist or m.instrument})" if m.title else m.instrument, live_app.market.symbol, hist,
                             root / m.instrument, root / (hist or m.instrument), live_app.session_calendar(), m.enabled, holidays)
    return out


def create_app(cfg: AppConfig, config_dir: Path | str | None = None, dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="ARVEN API", version="1", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware, allow_origins=[], allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_methods=["GET", "POST", "DELETE"], allow_headers=["content-type"],
    )
    data_dir = cfg.data.data_dir
    paper_root = data_dir / "paper"
    markets = web_markets(cfg, config_dir)
    market_param = Query("btc", pattern=r"^[a-z0-9_]{1,40}$")

    def resolve(market: str) -> WebMarket:
        if market not in markets:
            raise HTTPException(status_code=404, detail=f"unknown market {market!r}; known: {sorted(markets)}")
        return markets[market]

    def open_db() -> duckdb.DuckDBPyConnection:
        try:
            return duckdb.connect(str(cfg.data.database_path), read_only=True)
        except duckdb.IOException as exc:  # a writer (REST update / paper tick) currently holds the file
            raise HTTPException(status_code=503, detail=f"market database busy, retry in a moment ({exc})") from exc

    def heartbeat_state() -> dict[str, Any]:
        """The live signal process's heartbeat (``arven live run``), else the older Phase 5 paper runtime's."""
        live_hb, paper_hb = svc.read_json(data_dir / "live" / "heartbeat.json"), svc.read_json(paper_root / "heartbeat.json")
        hb = max((h for h in (live_hb, paper_hb) if h), key=lambda h: h.get("checked_at_ms", 0), default=None)
        now_ms = to_ms(utc_now())
        stale = hb is None or now_ms - hb.get("checked_at_ms", 0) > HEARTBEAT_MAX_AGE_MS
        source = None if hb is None else ("live" if hb is live_hb else "paper_runtime")
        return {"present": hb is not None, "stale": stale, "heartbeat": hb, "source": source}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "now_ms": to_ms(utc_now()), "read_only": True}

    @app.get("/api/markets")
    def markets_list() -> dict[str, Any]:
        return {"markets": [m.describe() for m in markets.values()], "default": "btc"}

    def overview_payload(market: str = "btc") -> dict[str, Any]:
        m = resolve(market)
        now_ms = to_ms(utc_now())
        last_bar = None
        try:
            con = open_db()
            try:
                last_bar = svc.last_bar_time_ms(con, m.symbol)
            finally:
                con.close()
        except HTTPException:
            pass
        signals_root = m.live_root / "signals"
        ids = svc.known_strategy_ids(signals_root)
        signals = svc.list_signals(signals_root, ids, limit=1000)
        day_ago = now_ms - 86_400_000
        # data age in trading time: a session market (gold) is not "stale" over a weekend
        age_ms = None if last_bar is None else int(m.calendar.trading_ms(now_ms)) - int(m.calendar.trading_ms(last_bar))
        market_open = bool(m.calendar.is_open(now_ms // 60_000 * 60_000))
        return {
            "now_ms": now_ms, "market": m.id, "symbol": m.symbol, "market_open": market_open, "last_1m_bar_open_ms": last_bar,
            "data_age_seconds": None if age_ms is None else age_ms / 1000.0,
            "data_stale": age_ms is None or age_ms > DATA_STALE_MS,
            "runtime": heartbeat_state(),
            "signals_total": len(signals), "signals_last_24h": sum(1 for s in signals if s["event_time_ms"] >= day_ago),
            "signals_open": sum(1 for s in signals if s["status"] in ("open", "partial", "pending")), "strategies": ids,
            "strategies_summary": svc.read_json(m.live_root / "paper" / "strategies_summary.json"),
            "note": "paper simulation on real market data; not an exchange account and not evidence of profitability",
        }

    @app.get("/api/overview")
    def overview(market: str = market_param) -> dict[str, Any]:
        return overview_payload(market)

    @app.get("/api/candles")
    def candles(tf: str = Query("15m"), limit: int = Query(500, ge=1, le=svc.MAX_CANDLES), before: int | None = None,
                market: str = market_param) -> dict[str, Any]:
        if tf not in svc.CANDLE_TIMEFRAMES:
            raise HTTPException(status_code=422, detail=f"tf must be one of {svc.CANDLE_TIMEFRAMES}")
        m = resolve(market)
        con = open_db()
        try:
            rows, source = svc.read_candles(con, m.symbol, tf, limit, before), m.symbol
            if not rows and m.history_symbol:  # older than the live feed: continue in the research history
                rows, source = svc.read_candles(con, m.history_symbol, tf, limit, before), m.history_symbol
            return {"symbol": m.symbol, "source": source, "timeframe": tf, "candles": rows}
        finally:
            con.close()

    @app.get("/api/sessions")
    def sessions() -> dict[str, Any]:
        """Every market's open/closed state (its real session calendar) and the four trading centres' working hours."""
        now_ms = to_ms(utc_now())
        return {
            "now_ms": now_ms,
            "markets": [{"id": m.id, "label": m.label, "session": m.calendar.kind, **ses.market_state(m.calendar, now_ms, m.holidays),
                         "next_holiday": ses.next_holiday(m.holidays, now_ms)} for m in markets.values()],
            "centres": [ses.centre_status(c, now_ms) for c in ses.CENTRES],
            "note": "centres: conventional local working hours, Monday to Friday - context only, not an exchange schedule",
        }

    activity_cache: dict[tuple[str, int], tuple[int, dict[str, Any]]] = {}  # a year of hourly ranges barely moves in an hour

    @app.get("/api/activity")
    def activity(market: str = market_param, days: int = Query(365, ge=7, le=1000)) -> dict[str, Any]:
        """Mean 1h range by weekday and hour (UTC) over the trailing ``days``, from the feed with more bars there."""
        m = resolve(market)
        now_ms = to_ms(utc_now())
        cached = activity_cache.get((m.id, days))
        if cached is not None and now_ms - cached[0] < ACTIVITY_CACHE_MS:
            return cached[1]
        con = open_db()
        try:
            best: tuple[str, list[tuple]] | None = None
            for symbol in (m.symbol, m.history_symbol):
                if symbol is None:
                    continue
                rows = svc.read_hourly_bars(con, symbol, now_ms - days * 86_400_000)
                if best is None or len(rows) > len(best[1]):
                    best = (symbol, rows)
        finally:
            con.close()
        assert best is not None
        symbol, rows = best
        cols = list(zip(*rows, strict=True)) if rows else [[], [], [], [], []]
        grid = ses.activity_grid(*(np.asarray(c) for c in cols), now_ms=now_ms)
        payload = {"market": m.id, "source": symbol, "days": days, "timezone": "UTC", "weekday_start": "monday", **grid,
                   "note": "mean (high - low) / open of completed 1h bars - how much the price moved, not which way; past, not a forecast"}
        activity_cache[(m.id, days)] = (now_ms, payload)
        return payload

    @app.get("/api/signals")
    def signals(strategy: str | None = None, limit: int = Query(100, ge=1, le=1000), market: str = market_param) -> dict[str, Any]:
        signals_root = resolve(market).live_root / "signals"
        ids = svc.known_strategy_ids(signals_root)
        if strategy is not None and strategy not in ids:
            return {"signals": []}
        return {"signals": svc.list_signals(signals_root, ids, limit, strategy)}

    @app.get("/api/signals/{signal_id}")
    def signal(signal_id: str, market: str = market_param) -> dict[str, Any]:
        signals_root = resolve(market).live_root / "signals"
        found = svc.signal_detail(signals_root, svc.known_strategy_ids(signals_root), signal_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown signal id")
        return found

    @app.get("/api/strategies")
    def strategies(market: str = market_param) -> dict[str, Any]:
        m = resolve(market)
        return {"forward_summary": svc.read_json(m.live_root / "paper" / "strategies_summary.json"),
                "strategies": svc.known_strategy_ids(m.live_root / "signals")}

    @app.get("/api/screener")
    def screener() -> dict[str, Any]:
        rows = []
        con = open_db()
        try:
            for m in markets.values():
                row = svc.screener_row(con, m.symbol) or (svc.screener_row(con, m.history_symbol) if m.history_symbol else None)
                if row:
                    rows.append({**row, "market": m.id, "label": m.label})
        finally:
            con.close()
        return {
            "supported_symbols": [m.symbol for m in markets.values()], "rows": rows,
            "note": "the markets ARVEN follows (config/live.yaml); prices from stored bars, 24h window",
        }

    @app.get("/api/research")
    def research(market: str = market_param) -> dict[str, Any]:
        m = resolve(market)
        roots = (m.research_root,) if m.research_root == m.live_root else (m.research_root, m.live_root)
        return {"runs": sorted((r for root in roots for r in svc.research_runs(root)),
                               key=lambda r: str(r["created_at"] or r["run_id"]), reverse=True)}

    @app.get("/api/journal")
    def journal_list() -> dict[str, Any]:
        entries = jr.read_entries(data_dir)
        return {"entries": list(reversed(entries)), "stats": jr.stats(entries)}

    @app.post("/api/journal", status_code=201)
    def journal_add(payload: jr.JournalEntryIn) -> dict[str, Any]:
        return jr.add_entry(data_dir, payload)

    @app.delete("/api/journal/{entry_id}")
    def journal_delete(entry_id: str) -> dict[str, Any]:
        if not jr.delete_entry(data_dir, entry_id):
            raise HTTPException(status_code=404, detail="unknown journal entry")
        return {"deleted": entry_id}

    review_dir = data_dir / "s7_review"
    review_tfs = ("15m", "1h", "4h")

    @app.get("/api/s7/review")
    def s7_review(tf: str = Query("1h")) -> dict[str, Any]:
        if tf not in review_tfs:
            raise HTTPException(status_code=422, detail=f"tf must be one of {review_tfs}")
        payload = svc.read_json(review_dir / f"setups_{tf}.json")
        return payload if payload is not None else {"timeframe": tf, "setups": [], "total_setups": 0}

    @app.get("/api/s7/labels")
    def s7_labels(tf: str = Query("1h")) -> dict[str, Any]:
        if tf not in review_tfs:
            raise HTTPException(status_code=422, detail=f"tf must be one of {review_tfs}")
        return {"labels": svc.read_json(review_dir / f"labels_{tf}.json") or {}}

    @app.post("/api/s7/labels")
    def s7_label(payload: jr.ReviewLabelIn) -> dict[str, Any]:
        tf = payload.setup_id.split("-", 1)[0]
        if tf not in review_tfs:
            raise HTTPException(status_code=422, detail="unknown setup id")
        path = review_dir / f"labels_{tf}.json"
        labels = svc.read_json(path) or {}
        labels[payload.setup_id] = {"verdict": payload.verdict, "note": payload.note, "at_ms": to_ms(utc_now())}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(labels, indent=1, sort_keys=True), encoding="utf-8")
        return {"saved": payload.setup_id, "count": len(labels)}

    study_periods = ("development", "validation")

    @app.get("/api/s7/trades")
    def s7_trades(period: str = Query("development"), market: str = market_param) -> dict[str, Any]:
        """Every trade of the development-selected S7 configuration (``scripts/s7_trades_export.py``), read-only."""
        if period not in study_periods:
            raise HTTPException(status_code=422, detail=f"period must be one of {study_periods}")
        payload = svc.read_json(resolve(market).research_root / "s7_study" / f"trades_{period}.json")
        return payload if payload is not None else {"period": period, "trades": [], "summary": None}

    trade_periods = ("development", "validation", "devval", "test", "forward")

    @app.get("/api/strategy_trades/index")
    def strategy_trades_index(market: str = market_param) -> dict[str, Any]:
        """Which strategies and periods have exported trades (``scripts/strategy_trades_export.py``), with summaries."""
        return {"entries": svc.read_json(resolve(market).research_root / "strategy_trades" / "index.json") or []}

    @app.get("/api/strategy_trades")
    def strategy_trades(strategy: str = Query(..., pattern=r"^[a-z0-9_]{1,40}$"), period: str = Query("development"),
                        market: str = market_param) -> dict[str, Any]:
        if period not in trade_periods:
            raise HTTPException(status_code=422, detail=f"period must be one of {trade_periods}")
        payload = svc.read_json(resolve(market).research_root / "strategy_trades" / strategy / f"{period}.json")
        return payload if payload is not None else {"strategy": strategy, "period": period, "trades": [], "summary": None}

    trade_labels_path = data_dir / "s7_study" / "trade_labels.json"

    @app.get("/api/s7/trade_labels")
    def s7_trade_labels() -> dict[str, Any]:
        return {"labels": svc.read_json(trade_labels_path) or {}}

    @app.post("/api/s7/trade_labels")
    def s7_trade_label(payload: jr.TradeLabelIn) -> dict[str, Any]:
        """The owner's verdict on one trade - the third write path (next to the journal and the setup labels)."""
        labels = svc.read_json(trade_labels_path) or {}
        labels[payload.trade_id] = {"verdict": payload.verdict, "note": payload.note, "at_ms": to_ms(utc_now())}
        trade_labels_path.parent.mkdir(parents=True, exist_ok=True)
        trade_labels_path.write_text(json.dumps(labels, indent=1, sort_keys=True), encoding="utf-8")
        return {"saved": payload.trade_id, "count": len(labels)}

    @app.get("/api/telegram")
    def telegram() -> dict[str, Any]:
        tcfg = load_telegram_config(config_dir)
        counts: dict[str, int] = {}
        try:
            con = open_db()
            try:
                counts = svc.outbox_counts(con)
            finally:
                con.close()
        except (HTTPException, duckdb.Error):
            pass
        return {
            "dry_run": tcfg.dry_run, "token_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
            "allowed_chats": len(allowed_chat_ids()), "outbox": counts,
        }

    @app.get("/api/stream")
    async def stream(request: Request, interval: float = Query(5.0, ge=0.2, le=60.0), max_events: int = Query(0, ge=0, le=100000),
                     market: str = market_param) -> StreamingResponse:
        resolve(market)

        async def gen():
            sent = 0
            while not await request.is_disconnected():
                payload = await asyncio.to_thread(overview_payload, market)
                yield f"event: overview\ndata: {json.dumps(payload)}\n\n"
                sent += 1
                if max_events and sent >= max_events:
                    break
                await asyncio.sleep(interval)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    dist = dist_dir if dist_dir is not None else Path(__file__).resolve().parents[3] / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app
