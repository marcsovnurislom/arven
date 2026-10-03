"""Shared offline fake for Binance's public REST API (klines, fundingRate) - no sockets, used by the
binance_rest / rest_ingestion / paper test suites."""

from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlparse


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


def kline_row(open_time_ms: int) -> list:
    close = open_time_ms + 60_000 - 1
    return [open_time_ms, "100.00", "101.00", "99.00", "100.50", "12.5", close, "1256.25", 42, "6.0", "603.0", "0"]


def funding_row(symbol: str, t_ms: int, rate: float) -> dict:
    return {"symbol": symbol, "fundingTime": t_ms, "fundingRate": f"{rate:.8f}", "markPrice": "100.0"}


class FakeBinanceRestOpener:
    """Serves ``/fapi/v1/klines`` and ``/fapi/v1/fundingRate`` from in-memory series, honouring
    startTime/endTime/limit exactly like the real API (endTime inclusive, limit caps the page)."""

    def __init__(self, kline_opens: list[int], funding_times: list[int]):
        self.kline_opens = kline_opens
        self.funding_times = funding_times
        self.calls: list[str] = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.calls.append(url)
        parsed = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        start, end, limit = int(q["startTime"]), int(q["endTime"]), int(q["limit"])
        if parsed.path == "/fapi/v1/klines":
            rows = [kline_row(t) for t in self.kline_opens if start <= t <= end][:limit]
            return FakeResponse(json.dumps(rows).encode())
        if parsed.path == "/fapi/v1/fundingRate":
            rows = [funding_row(q["symbol"], t, 0.0001) for t in self.funding_times if start <= t <= end][:limit]
            return FakeResponse(json.dumps(rows).encode())
        raise AssertionError(f"unexpected path {parsed.path}")
