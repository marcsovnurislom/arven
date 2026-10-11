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

- ``GET /futures/data/openInterestHist`` / ``topLongShortAccountRatio`` / ``topLongShortPositionRatio`` /
  ``globalLongShortAccountRatio`` (``period=5m``): arrays of ``{"timestamp", ...}`` with ``sumOpenInterest`` /
  ``sumOpenInterestValue`` or ``longShortRatio``; ``takerlongshortRatio``: ``{"timestamp", "buySellRatio", ...}``.
  Binance serves only the latest 30 days, at most 500 rows per call.

Open interest and the long/short ratios ("metrics" in the bulk layout) were not fetched in Stage 8 (scope decision
D2); the live signal loop needs them (strategy "Crowded Shorts" uses ``oi_z``), so :func:`fetch_open_interest_stats`
adds them. **Timestamp mapping, measured, not assumed** (2026-10-11, 241 overlapping 5-minute rows of 2026-10-09
compared with the stored bulk ``metrics`` file): the bulk row with ``create_time = T`` equals the REST rows of
``openInterestHist`` / ``top*`` / ``globalLongShortAccountRatio`` stamped ``T + 5 min`` (open interest bit-identical,
ratios equal to the REST's 4 decimals) and the ``takerlongshortRatio`` row stamped ``T`` (equal to 4 decimals). The
rows are therefore stored under the bulk convention (``ts_ms = T``), so live and historical data are one series.
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


REST_STATS_LIMIT = 500
STATS_PERIOD_MS = 300_000
STATS_SHIFT_MS = 300_000  # REST open-interest/ratio timestamp = bulk create_time + 5 min (see the module docstring)
_STATS_ENDPOINTS = (  # (path, field, bulk column, timestamp shift)
    ("openInterestHist", "sumOpenInterest", "sum_open_interest", STATS_SHIFT_MS),
    ("openInterestHist", "sumOpenInterestValue", "sum_open_interest_value", STATS_SHIFT_MS),
    ("topLongShortAccountRatio", "longShortRatio", "count_toptrader_long_short_ratio", STATS_SHIFT_MS),
    ("topLongShortPositionRatio", "longShortRatio", "sum_toptrader_long_short_ratio", STATS_SHIFT_MS),
    ("globalLongShortAccountRatio", "longShortRatio", "count_long_short_ratio", STATS_SHIFT_MS),
    ("takerlongshortRatio", "buySellRatio", "sum_taker_long_short_vol_ratio", 0),
)
OI_COLUMNS = tuple(dict.fromkeys(col for _, _, col, _ in _STATS_ENDPOINTS))


@dataclass(frozen=True, slots=True)
class RestOpenInterest:
    ts_ms: int  # bulk convention (create_time), see the module docstring
    values: dict[str, float | None]  # OI_COLUMNS -> value (None if that endpoint had no row)


def fetch_open_interest_stats(
    downloader: Downloader, base_url: str, symbol: str, start_ms: int, end_ms: int, limit: int = REST_STATS_LIMIT,
) -> list[RestOpenInterest]:
    """5-minute open interest + long/short ratios with bulk ``ts_ms`` in ``[start_ms, end_ms)``, oldest first. A row is
    returned only if its open interest exists; a missing ratio is ``None`` (NULL, the features are NaN-tolerant)."""
    by_ts: dict[int, dict[str, float | None]] = {}
    fetched: dict[str, list] = {}
    for path, field, col, shift in _STATS_ENDPOINTS:
        key = f"{path}:{shift}"
        if key not in fetched:
            fetched[key] = list(_get(downloader, base_url, f"/futures/data/{path}", {  # type: ignore[arg-type]
                "symbol": symbol, "period": "5m", "startTime": start_ms + shift, "endTime": end_ms + shift - 1, "limit": limit,
            }))
        for row in fetched[key]:
            ts = int(row["timestamp"]) - shift
            if start_ms <= ts < end_ms and ts % STATS_PERIOD_MS == 0:
                by_ts.setdefault(ts, {})[col] = float(row[field])
    return [
        RestOpenInterest(ts, {c: vals.get(c) for c in OI_COLUMNS})
        for ts, vals in sorted(by_ts.items()) if vals.get("sum_open_interest") is not None
    ]


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
