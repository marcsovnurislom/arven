"""Cross-check derived higher-timeframe bars against Binance's native klines (stored in ``ohlcv_native``).

For a session market (gold) only buckets that lie wholly inside trading hours are compared: Binance's native
klines also contain the weekend and halt minutes, which ARVEN deliberately does not store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import duckdb

from arven.core.sessions import SessionCalendar
from arven.core.time import to_ms
from arven.core.timeframes import Timeframe

VOLUME_REL_TOLERANCE = 1e-9


@dataclass
class CrossCheckResult:
    timeframe: str
    native_bars: int
    derived_bars: int
    compared: int
    missing_in_derived: int
    missing_in_native: int
    incomplete_derived: int
    price_mismatches: int
    trade_count_mismatches: int
    volume_mismatches: int
    max_abs_price_diff: float
    max_rel_volume_diff: float
    examples: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.native_bars > 0
            and self.missing_in_derived == 0
            and self.missing_in_native == 0
            and self.price_mismatches == 0
            and self.trade_count_mismatches == 0
            and self.volume_mismatches == 0
        )


def compare(
    con: duckdb.DuckDBPyConnection, symbol: str, tf: Timeframe, start: datetime, end: datetime,
    calendar: SessionCalendar | None = None,
) -> CrossCheckResult:
    lo, hi = to_ms(start), to_ms(end)
    tol = VOLUME_REL_TOLERANCE
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _xc AS
        SELECT coalesce(n.open_time_ms, d.open_time_ms) AS open_time_ms,
               n.open_time_ms IS NOT NULL AS in_native, d.open_time_ms IS NOT NULL AS in_derived,
               d.is_complete,
               n.open AS n_open, d.open AS d_open, n.high AS n_high, d.high AS d_high,
               n.low AS n_low, d.low AS d_low, n.close AS n_close, d.close AS d_close,
               n.trade_count AS n_trades, d.trade_count AS d_trades,
               n.volume AS n_vol, d.volume AS d_vol, n.quote_volume AS n_qvol, d.quote_volume AS d_qvol,
               n.taker_buy_volume AS n_tbv, d.taker_buy_volume AS d_tbv,
               n.taker_buy_quote_volume AS n_tbqv, d.taker_buy_quote_volume AS d_tbqv
        FROM (SELECT * FROM ohlcv_native WHERE symbol = $sym AND timeframe = $tf
              AND open_time_ms >= $lo AND open_time_ms < $hi) n
        FULL OUTER JOIN (SELECT * FROM ohlcv WHERE symbol = $sym AND timeframe = $tf
              AND open_time_ms >= $lo AND open_time_ms < $hi) d
        USING (open_time_ms)
        """,
        {"sym": symbol, "tf": tf.value, "lo": lo, "hi": hi},
    )
    if calendar is not None and not calendar.always_open:
        opens = calendar.bar_opens(tf, lo, hi)
        full = opens[calendar.expected_minutes(tf, opens) == tf.ms // Timeframe.M1.ms]
        con.execute("CREATE OR REPLACE TEMP TABLE _full AS SELECT unnest(?::BIGINT[]) AS t", [[int(x) for x in full]])
        con.execute("DELETE FROM _xc WHERE open_time_ms NOT IN (SELECT t FROM _full)")
        con.execute("DROP TABLE _full")

    def rel(a: str, b: str) -> str:
        return f"abs({a} - {b}) / greatest(abs({a}), 1e-12)"

    vol_rel = f"greatest({rel('n_vol', 'd_vol')}, {rel('n_qvol', 'd_qvol')}, {rel('n_tbv', 'd_tbv')}, {rel('n_tbqv', 'd_tbqv')})"
    price_diff = "greatest(abs(n_open - d_open), abs(n_high - d_high), abs(n_low - d_low), abs(n_close - d_close))"
    row = con.execute(
        f"""
        SELECT count(*) FILTER (in_native),
               count(*) FILTER (in_derived),
               count(*) FILTER (in_native AND in_derived),
               count(*) FILTER (in_native AND NOT in_derived),
               count(*) FILTER (in_derived AND NOT in_native),
               count(*) FILTER (in_derived AND NOT is_complete),
               count(*) FILTER (in_native AND in_derived AND {price_diff} <> 0),
               count(*) FILTER (in_native AND in_derived AND n_trades <> d_trades),
               count(*) FILTER (in_native AND in_derived AND {vol_rel} > {tol}),
               coalesce(max({price_diff}) FILTER (in_native AND in_derived), 0),
               coalesce(max({vol_rel}) FILTER (in_native AND in_derived), 0)
        FROM _xc
        """
    ).fetchone()
    examples_rows = con.execute(
        f"""
        SELECT open_time_ms, in_native, in_derived, n_close, d_close, n_vol, d_vol, n_trades, d_trades
        FROM _xc
        WHERE NOT (in_native AND in_derived) OR {price_diff} <> 0 OR n_trades <> d_trades OR {vol_rel} > {tol}
        ORDER BY open_time_ms LIMIT 5
        """
    ).fetchall()
    con.execute("DROP TABLE IF EXISTS _xc")
    names = ["open_time_ms", "in_native", "in_derived", "n_close", "d_close", "n_vol", "d_vol", "n_trades", "d_trades"]
    return CrossCheckResult(
        tf.value, *[int(v) for v in row[:9]], float(row[9]), float(row[10]),
        examples=[dict(zip(names, r)) for r in examples_rows],
    )
