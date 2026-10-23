"""Learning from mistakes, honestly (the owner's request, 2026-10-24): in which circumstances does a strategy lose or win?

For every trade this records the circumstances **known at its entry** (:func:`context_at`): the 4h and 1h trend, how
volatile the market was, the session and weekday, how near a FOMC / CPI / NFP release, how wide the stop was in ATR and
whether the entry chased a move or bought a pullback. :func:`report` then compares each circumstance with all the other
trades of the strategy. A circumstance is flagged only when it has at least ``MIN_TRADES`` trades **and** a seeded
bootstrap interval of (its mean R - the rest's mean R) excludes zero at a Bonferroni-corrected level - with ~20
circumstances per strategy some would look "bad" by luck alone, and a flag must not be luck.

Nothing changes a strategy here: a flagged circumstance becomes, at most, an idea for a rule that the owner approves
and that is then checked on fresh data. Pure functions over arrays, plus one loader of stored bars.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import duckdb
import numpy as np

from arven.core.macro_config import MacroEvent
from arven.features import indicators as ind

HOUR_MS = 3_600_000
H4_MS = 4 * HOUR_MS
DAY_MS = 24 * HOUR_MS
MIN_TRADES = 30  # a circumstance with fewer trades is shown, never flagged (the forward review rule's minimum)
ALPHA = 0.05  # family-wise, Bonferroni-split over every circumstance tested for one strategy
BOOT = 4000
SEED = 7
NEWS_WINDOW_MS = 2 * HOUR_MS

FEATURES: tuple[str, ...] = ("trend_4h", "trend_1h", "volatility", "session", "weekday", "news", "stop_atr", "move_24h")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class TfBars:
    """One timeframe's completed bars, ascending: open times and OHLC; ``tf_ms`` is the bar length."""

    tf_ms: int
    open_time_ms: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    def closed_by(self, t_ms: int) -> int:
        """Number of bars whose close (open + tf) is at or before ``t_ms``."""
        return int(np.searchsorted(self.open_time_ms + self.tf_ms, t_ms, side="right"))


def load_tf_bars(con: duckdb.DuckDBPyConnection, symbols: Sequence[str], timeframe: str, tf_ms: int) -> TfBars:
    """Complete stored bars of one timeframe for ``symbols`` (a history feed first, then a live one), merged by time."""
    rows: dict[int, tuple] = {}
    for symbol in symbols:
        for r in con.execute(
            "SELECT open_time_ms, high, low, close FROM ohlcv WHERE symbol = ? AND timeframe = ? AND is_complete ORDER BY open_time_ms",
            [symbol, timeframe],
        ).fetchall():
            rows.setdefault(int(r[0]), r)
    ordered = [rows[k] for k in sorted(rows)]
    if not ordered:
        z = np.array([], dtype=float)
        return TfBars(tf_ms, np.array([], dtype=np.int64), z, z, z)
    t, h, lo, c = (np.asarray(x) for x in zip(*ordered, strict=True))
    return TfBars(tf_ms, t.astype(np.int64), h.astype(float), lo.astype(float), c.astype(float))


def _trend(b: TfBars, n: int, side: int, period: int = 50) -> str:
    if n < period:
        return "unknown"
    closes = b.close[n - period:n]
    up = closes[-1] > closes.mean()
    return "with the trade" if (1 if up else -1) == side else "against the trade"


def context_at(t_ms: int, side: int, entry: float, stop: float, h1: TfBars, h4: TfBars, events: Sequence[MacroEvent]) -> dict[str, str]:
    """The circumstances of a trade entered at ``t_ms`` - only bars closed by then and the public release schedule."""
    n1, n4 = h1.closed_by(t_ms), h4.closed_by(t_ms)
    out = {"trend_4h": _trend(h4, n4, side), "trend_1h": _trend(h1, n1, side)}
    if n1 >= 24 * 30:
        a = max(0, n1 - 24 * 60)  # the last 60 days of closed 1h bars: enough for ATR(14) and its 30-day median
        atr = ind.atr(h1.high[a:n1], h1.low[a:n1], h1.close[a:n1], 14, 14)
        now, typical = atr[-1], float(np.nanmedian(atr[-24 * 30:]))
        ratio = now / typical if typical > 0 else np.nan
        out["volatility"] = "unknown" if not np.isfinite(ratio) else "calm" if ratio < 0.8 else "stormy" if ratio > 1.25 else "normal"
        dist = abs(entry - stop) / now if now > 0 else np.nan
        out["stop_atr"] = "unknown" if not np.isfinite(dist) else "tight (<1 ATR)" if dist < 1 else "wide (>2.5 ATR)" if dist > 2.5 else "normal (1-2.5 ATR)"
        past = h1.close[n1 - 24] if n1 >= 25 else np.nan
        move = side * (h1.close[n1 - 1] / past - 1) / (now / h1.close[n1 - 1]) if past > 0 else np.nan  # 24 h move, in 1h ATRs, in the trade's direction
        out["move_24h"] = "unknown" if not np.isfinite(move) else "chasing (>+3 ATR)" if move > 3 else "after a drop (<-3 ATR)" if move < -3 else "quiet (+-3 ATR)"
    else:
        out |= {"volatility": "unknown", "stop_atr": "unknown", "move_24h": "unknown"}
    hour = (t_ms // HOUR_MS) % 24
    out["session"] = "00-07 Asia" if hour < 7 else "07-13 Europe" if hour < 13 else "13-21 US" if hour < 21 else "21-24 late"
    out["weekday"] = WEEKDAYS[int((t_ms // DAY_MS + 3) % 7)]  # 1970-01-01 was a Thursday
    before = any(0 <= e.scheduled_at_ms - t_ms <= NEWS_WINDOW_MS for e in events)
    after = any(0 < t_ms - e.scheduled_at_ms <= NEWS_WINDOW_MS for e in events)
    out["news"] = "within 2 h before a release" if before else "within 2 h after a release" if after else "no release near"
    return out


def _boot_diff(a: np.ndarray, b: np.ndarray, rng: np.random.Generator, level: float) -> tuple[float, float]:
    ia = rng.integers(0, len(a), size=(BOOT, len(a)))
    ib = rng.integers(0, len(b), size=(BOOT, len(b)))
    d = a[ia].mean(axis=1) - b[ib].mean(axis=1)
    lo, hi = np.percentile(d, [100 * level / 2, 100 * (1 - level / 2)])
    return float(lo), float(hi)


def report(rows: Sequence[dict[str, Any]], features: Sequence[str] = FEATURES) -> dict[str, Any]:
    """Per circumstance: trades, win rate, mean and total R, and - with enough trades - the corrected interval of its
    mean R minus the rest's; ``flag`` is ``worse`` / ``better`` when that interval excludes zero, else ``None``."""
    r = np.array([float(x["net_r"]) for x in rows])
    groups = [(f, v) for f in features for v in sorted({str(x[f]) for x in rows}) if v != "unknown"]
    tested = [(f, v) for f, v in groups if sum(1 for x in rows if x[f] == v) >= MIN_TRADES and len(rows) - sum(1 for x in rows if x[f] == v) >= MIN_TRADES]
    level = ALPHA / max(1, len(tested))
    rng = np.random.default_rng(SEED)
    out: dict[str, Any] = {"trades": len(rows), "mean_r": float(r.mean()) if len(r) else None, "total_r": float(r.sum()),
                           "tested": len(tested), "level": level, "min_trades": MIN_TRADES, "features": {}}
    for f in features:
        cells = {}
        for v in sorted({str(x[f]) for x in rows}):
            mask = np.array([x[f] == v for x in rows])
            g = r[mask]
            cell: dict[str, Any] = {"trades": int(mask.sum()), "win_rate": float(np.mean(g > 0)), "mean_r": float(g.mean()), "total_r": float(g.sum()),
                                    "diff_low": None, "diff_high": None, "flag": None}
            if (f, v) in tested:
                lo, hi = _boot_diff(g, r[~mask], rng, level)
                cell |= {"diff_low": lo, "diff_high": hi, "flag": "worse" if hi < 0 else "better" if lo > 0 else None}
            cells[v] = cell
        out["features"][f] = cells
    return out


__all__ = ["FEATURES", "MIN_TRADES", "TfBars", "context_at", "load_tf_bars", "report"]
