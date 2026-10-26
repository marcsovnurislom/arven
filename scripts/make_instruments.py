"""Write config/instruments/<X>.yaml for the markets added on 2026-10-27 (owner: "add the ten best-known pairs and coins").

Run once; the files are then ordinary checked-in config. Crypto: Binance USD-M perpetuals (the BTC pipeline: bulk
history + REST tail), costed with the Binance taker profile (config/costs.yaml - the venue the data comes from).
Silver: Binance XAGUSDT live + Dukascopy XAGUSD history, like gold. Forex: Dukascopy history; live minutes from
Kraken (arven.data.kraken_live), the only free real-time EUR/USD and GBP/USD feed found with a trade every minute.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "config" / "instruments"

CRYPTO = {"ETHUSDT": "Ethereum", "SOLUSDT": "Solana", "XRPUSDT": "XRP", "BNBUSDT": "BNB", "DOGEUSDT": "Dogecoin",
          "ADAUSDT": "Cardano", "LINKUSDT": "Chainlink"}

CRYPTO_TMPL = """# {name} ({symbol}) on Binance USD-M futures: the same pipeline as BTC (bulk history from data.binance.vision, REST tail
# for live). Added 2026-10-27. Costs: Binance taker profile (config/costs.yaml, 5 bps + volatility slippage + real
# funding) - the venue the prices come from; a CFD broker's spread for this coin was not checked.
market:
  symbol: {symbol}
"""

DUKA_TMPL = """# {name} ({symbol}) history for research: Dukascopy 1m BID/ASK candles -> mid price, 2020 onward. Added 2026-10-27.
# Live minutes: {live}.
market:
  exchange: dukascopy
  market_type: spot_otc
  symbol: {symbol}
  session: {session}
  has_funding: false
  has_trade_flow: false

costs_file: {costs}

dukascopy:
  base_url: https://datafeed.dukascopy.com/datafeed
  instrument: {symbol}
  point: {point}
  request_interval_seconds: 1.0
  workers: 4
  timeout_seconds: 30
  max_attempts: 6
  backoff_max_seconds: 60
"""

XAG_LIVE = """# Silver on Binance USD-M futures (XAGUSDT perpetual, listed 2026-01-07): the live feed for silver signals, like XAUUSDT
# for gold. Same CME metals session calendar as the Dukascopy XAGUSD history. Added 2026-10-27.
market:
  exchange: binance
  market_type: usdm_perpetual
  symbol: XAGUSDT
  session: cme_metals
  has_funding: false

costs_file: costs_cfd_silver.yaml
"""


def main() -> None:
    for sym, name in CRYPTO.items():
        (ROOT / f"{sym}.yaml").write_text(CRYPTO_TMPL.format(name=name, symbol=sym), encoding="utf-8", newline="\n")
    (ROOT / "XAGUSD.yaml").write_text(DUKA_TMPL.format(name="Silver", symbol="XAGUSD", session="cme_metals", point=1000,
                                                        costs="costs_cfd_silver.yaml", live="Binance XAGUSDT (config/instruments/XAGUSDT.yaml)"),
                                      encoding="utf-8", newline="\n")
    (ROOT / "XAGUSDT.yaml").write_text(XAG_LIVE, encoding="utf-8", newline="\n")
    for sym, name in {"EURUSD": "Euro / US dollar", "GBPUSD": "British pound / US dollar"}.items():
        (ROOT / f"{sym}.yaml").write_text(DUKA_TMPL.format(name=name, symbol=sym, session="fx", point=100000, costs="costs_cfd_fx.yaml",
                                                            live="Kraken spot OHLC appended to this same symbol (arven.data.kraken_live)"),
                                          encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
