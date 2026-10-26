"""Why no strategy decides on 1m bars (2026-10-27): the round-trip cost against the size of a typical bar, per market.

For each market and timeframe (1m ... 1d) on the validation period (2023-07 -> 2025-01): the median bar range
(high - low) / open in bps, the round-trip cost of one trade in bps (2 x (taker fee + fixed slippage) of the market's
cost profile), and the cost as a share of the median range. A stop about one bar range away (a typical S7 / S4 stop on
that timeframe) pays the cost as a share of R, before any edge: above ~0.3 R per trade no plausible edge survives.
Research only; reads the database, writes data/research/one_minute_costs.json.

Usage: ARVEN_DB_WAIT_SECONDS=300 PYTHONPATH=src python scripts/research/one_minute_costs.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from arven.core.config import load_config
from arven.data.reader import open_readonly

MARKETS = {"BTC": None, "Gold": "XAUUSD", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT", "BNB": "BNBUSDT", "DOGE": "DOGEUSDT",
           "ADA": "ADAUSDT", "LINK": "LINKUSDT", "Silver": "XAGUSD", "EUR/USD": "EURUSD", "GBP/USD": "GBPUSD"}
CFD_BTC = "config/costs_cfd_justmarkets.yaml"
TFS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
LO, HI = 1688169600000, 1735689600000  # validation 2023-07-01 -> 2025-01-01


def main() -> None:
    import yaml

    from arven.core.config import CostsConfig

    out = {}
    for label, inst in MARKETS.items():
        app = load_config(instrument=inst)
        costs = CostsConfig.model_validate(yaml.safe_load(Path(CFD_BTC).read_text(encoding="utf-8"))) if inst is None else app.costs
        rt_bps = 2 * ((costs.fees.taker_fee_bps or 0) + costs.slippage.fixed_bps)
        con = open_readonly(app.data.database_path)
        try:
            row = {}
            for tf in TFS:
                sql = ("SELECT (high - low) / open FROM ohlcv_1m WHERE symbol = ? AND open_time_ms >= ? AND open_time_ms < ?" if tf == "1m" else
                       "SELECT (high - low) / open FROM ohlcv WHERE symbol = ? AND timeframe = ? AND is_complete AND open_time_ms >= ? AND open_time_ms < ?")
                args = [app.market.symbol, LO, HI] if tf == "1m" else [app.market.symbol, tf, LO, HI]
                r = np.asarray([x[0] for x in con.execute(sql, args).fetchall()], dtype=float)
                if len(r) == 0:
                    row[tf] = None
                    continue
                med = float(np.median(r)) * 1e4
                row[tf] = {"bars": int(len(r)), "median_range_bps": med, "cost_share_of_range": rt_bps / med if med > 0 else None}
        finally:
            con.close()
        out[label] = {"round_trip_cost_bps": rt_bps, "timeframes": row}
        cells = " ".join(f"{tf}:{v['cost_share_of_range']:.2f}" if v and v["cost_share_of_range"] is not None else f"{tf}:-" for tf, v in row.items())
        print(f"{label:8s} cost {rt_bps:5.1f} bps  cost / median range -> {cells}", flush=True)
    path = Path("data/research/one_minute_costs.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("saved", path)


if __name__ == "__main__":
    main()
