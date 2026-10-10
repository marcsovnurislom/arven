"""The ARVEN HTTP API (docs/ARVEN_MASTER_PROMPT.md section 5.6): read-only over stored artifacts and market data, plus the
separate manual journal. Binds to 127.0.0.1 by default (``arven web``), CORS is limited to localhost origins, and there is no
endpoint that writes market data or places an order (CLAUDE.md rule 12). Missing data is reported honestly (empty lists /
``null``), never replaced by invented values."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from arven.core.config import AppConfig
from arven.core.telegram_config import allowed_chat_ids, load_telegram_config
from arven.core.time import to_ms, utc_now
from arven.web import journal as jr
from arven.web import service as svc

HEARTBEAT_MAX_AGE_MS = 5 * 60_000
DATA_STALE_MS = 3 * 3_600_000


def create_app(cfg: AppConfig, config_dir: Path | str | None = None, dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="ARVEN API", version="1", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware, allow_origins=[], allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_methods=["GET", "POST", "DELETE"], allow_headers=["content-type"],
    )
    data_dir = cfg.data.data_dir
    signals_root, paper_root = data_dir / "signals", data_dir / "paper"
    symbol = cfg.market.symbol

    def open_db() -> duckdb.DuckDBPyConnection:
        try:
            return duckdb.connect(str(cfg.data.database_path), read_only=True)
        except duckdb.IOException as exc:  # a writer (REST update / paper tick) currently holds the file
            raise HTTPException(status_code=503, detail=f"market database busy, retry in a moment ({exc})") from exc

    def heartbeat_state() -> dict[str, Any]:
        hb = svc.read_json(paper_root / "heartbeat.json")
        now_ms = to_ms(utc_now())
        stale = hb is None or now_ms - hb.get("checked_at_ms", 0) > HEARTBEAT_MAX_AGE_MS
        return {"present": hb is not None, "stale": stale, "heartbeat": hb}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "now_ms": to_ms(utc_now()), "read_only": True}

    def overview_payload() -> dict[str, Any]:
        now_ms = to_ms(utc_now())
        last_bar = None
        try:
            con = open_db()
            try:
                last_bar = svc.last_bar_time_ms(con, symbol)
            finally:
                con.close()
        except HTTPException:
            pass
        ids = svc.known_strategy_ids(signals_root)
        signals = svc.list_signals(signals_root, ids, limit=1000)
        day_ago = now_ms - 86_400_000
        return {
            "now_ms": now_ms, "symbol": symbol, "last_1m_bar_open_ms": last_bar,
            "data_age_seconds": None if last_bar is None else (now_ms - last_bar) / 1000.0,
            "data_stale": last_bar is None or now_ms - last_bar > DATA_STALE_MS,
            "runtime": heartbeat_state(),
            "signals_total": len(signals), "signals_last_24h": sum(1 for s in signals if s["event_time_ms"] >= day_ago),
            "signals_open": sum(1 for s in signals if s["status"] != "closed"), "strategies": ids,
            "strategies_summary": svc.read_json(paper_root / "strategies_summary.json"),
            "note": "paper simulation on real market data; not an exchange account and not evidence of profitability",
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        return overview_payload()

    @app.get("/api/candles")
    def candles(tf: str = Query("15m"), limit: int = Query(500, ge=1, le=svc.MAX_CANDLES), before: int | None = None) -> dict[str, Any]:
        if tf not in svc.CANDLE_TIMEFRAMES:
            raise HTTPException(status_code=422, detail=f"tf must be one of {svc.CANDLE_TIMEFRAMES}")
        con = open_db()
        try:
            return {"symbol": symbol, "timeframe": tf, "candles": svc.read_candles(con, symbol, tf, limit, before)}
        finally:
            con.close()

    @app.get("/api/signals")
    def signals(strategy: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
        ids = svc.known_strategy_ids(signals_root)
        if strategy is not None and strategy not in ids:
            return {"signals": []}
        return {"signals": svc.list_signals(signals_root, ids, limit, strategy)}

    @app.get("/api/signals/{signal_id}")
    def signal(signal_id: str) -> dict[str, Any]:
        found = svc.signal_detail(signals_root, svc.known_strategy_ids(signals_root), signal_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown signal id")
        return found

    @app.get("/api/strategies")
    def strategies() -> dict[str, Any]:
        return {"forward_summary": svc.read_json(paper_root / "strategies_summary.json"), "strategies": svc.known_strategy_ids(signals_root)}

    @app.get("/api/screener")
    def screener() -> dict[str, Any]:
        con = open_db()
        try:
            row = svc.screener_row(con, symbol)
        finally:
            con.close()
        return {
            "supported_symbols": [symbol], "rows": [row] if row else [],
            "note": "single-symbol MVP (BTC/USDT); multi-symbol screening is a later phase and is not faked here",
        }

    @app.get("/api/research")
    def research() -> dict[str, Any]:
        return {"runs": svc.research_runs(data_dir)}

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
    async def stream(request: Request, interval: float = Query(5.0, ge=0.2, le=60.0), max_events: int = Query(0, ge=0, le=100000)) -> StreamingResponse:
        async def gen():
            sent = 0
            while not await request.is_disconnected():
                payload = await asyncio.to_thread(overview_payload)
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
