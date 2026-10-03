"""Binance public REST (https://fapi.binance.com), USD-M futures - incremental ("tail") updates only.

Unlike ``binance_bulk`` (whole monthly/daily files, used for the historical backfill), this talks to the
live REST API to fetch whatever closed bars/funding settlements exist since the last stored row. Public
market-data endpoints only: no API key, no account/order endpoints (CLAUDE.md rule 12 - no real execution
code in the MVP). Reuses ``Downloader.fetch_bytes`` for the actual HTTP (retries, backoff, timeouts) rather
than a second HTTP client.

Response shapes (documented here since there is no local schema file for them, unlike the bulk CSVs):

- ``GET /fapi/v1/klines``: array of
  ``[openTime, open, high, low, close, volume, closeTime, quoteVolume, numTrades,
    takerBuyBaseVolume, takerBuyQuoteVolume, ignore]`` - the same 12 fields ``binance_bulk.KLINE_COLUMNS``
  already names, in the same order.
- ``GET /fapi/v1/fundingRate``: array of ``{"symbol", "fundingTime", "fundingRate", "markPrice"}``. The
  funding interval is not included; Binance's own stored bulk data for this symbol has always reported 8h
  (``current_state.md``'s "Final verification"), so callers pass the configured
  ``costs.funding.default_interval_hours`` rather than a value this module invents.

Open interest / top-trader / taker long-short ratios ("metrics" in the bulk layout) are deliberately **not**
fetched here (Stage 8 scope decision): they are optional, NaN-tolerant features throughout the stack
(``oi_available``), so the forward period simply carries stale/NaN OI exactly as the existing staleness
policy already handles for any other gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode

from arven.data.download import Downloader

KLINE_FIELDS = (
    "open_time_ms", "open", "high", "low", "close", "volume", "close_time_ms",
    "quote_volume", "trade_count", "taker_buy_volume", "taker_buy_quote_volume",
)
REST_KLINE_LIMIT = 1000
REST_FUNDING_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class RestKline:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int
    quote_volume: float
    trade_count: int
    taker_buy_volume: float
    taker_buy_quote_volume: float


@dataclass(frozen=True, slots=True)
class RestFunding:
    funding_time_ms: int
    funding_rate: float


def _get(downloader: Downloader, base_url: str, path: str, params: dict[str, object]) -> object:
    url = f"{base_url.rstrip('/')}{path}?{urlencode(params)}"
    return json.loads(downloader.fetch_bytes(url))


def fetch_klines(
    downloader: Downloader, base_url: str, symbol: str, interval: str, start_ms: int, end_ms: int,
    limit: int = REST_KLINE_LIMIT,
) -> list[RestKline]:
    """Klines with ``open_time`` in ``[start_ms, end_ms)``, oldest first. Binance returns at most ``limit``
    rows per call; callers needing more must page themselves (``RestIngestor`` does)."""
    raw = _get(downloader, base_url, "/fapi/v1/klines", {
        "symbol": symbol, "interval": interval, "startTime": start_ms, "endTime": end_ms - 1, "limit": limit,
    })
    out = []
    for row in raw:
        k = RestKline(*(int(row[i]) if KLINE_FIELDS[i].endswith("_ms") or i == 8 else float(row[i]) for i in range(11)))
        if not (start_ms <= k.open_time_ms < end_ms):
            continue  # defensive: Binance's endTime is inclusive, never trust it past our own bound
        out.append(k)
    return out


def fetch_funding_rate(
    downloader: Downloader, base_url: str, symbol: str, start_ms: int, end_ms: int, limit: int = REST_FUNDING_LIMIT,
) -> list[RestFunding]:
    """Funding settlements with ``fundingTime`` in ``[start_ms, end_ms)``, oldest first."""
    raw = _get(downloader, base_url, "/fapi/v1/fundingRate", {
        "symbol": symbol, "startTime": start_ms, "endTime": end_ms - 1, "limit": limit,
    })
    out = []
    for row in raw:
        t = int(row["fundingTime"])
        if not (start_ms <= t < end_ms):
            continue
        out.append(RestFunding(t, float(row["fundingRate"])))
    return out
