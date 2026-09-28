# ARVEN

**ARVEN** is an AI-assisted decision-support system for financial markets, built as a university diploma project.

It analyses market data and produces one of three decision-support signals:

- `LONG`
- `SHORT`
- `NO_TRADE`

> ARVEN does **not** execute trades and does **not** guarantee profitability. It is a research and
> decision-support tool. All reported performance is historical/simulated and includes fees, slippage and funding.

## MVP scope

- Instrument: **BTC/USDT perpetual futures** (Binance USDⓈ-M, public market data)
- Timeframes: 5m, 15m, 1h, 4h
- Inputs: OHLCV, volume, technical indicators, funding rate, open interest, (later) news and macro events
- Components: data ingestion & storage, feature engineering, market regime detection, multiple
  independent strategies, ML signal filter, decision engine, risk engine, backtester, paper-signal loop
- Out of scope: real order execution, multi-asset, deep learning / RL, order-book modelling

## Status

Stage 1 (Foundations) implemented: core types, UTC/bar-time utilities, validated configuration, unit tests.
See [`docs/current_state.md`](docs/current_state.md).

```
.venv/Scripts/python.exe -m pytest      # run the test suite (Windows venv path)
```

## Documentation

| Document | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Permanent project rules and development principles |
| [`docs/architecture.md`](docs/architecture.md) | System architecture, data model, backtesting, ML, risk, LLM usage |
| [`docs/roadmap.md`](docs/roadmap.md) | Staged development plan |
| [`docs/current_state.md`](docs/current_state.md) | Current development state (handover for humans and AI agents) |

## Planned tech stack (not yet installed)

Python 3.13 · pandas / numpy · DuckDB (+ Parquet) · LightGBM & scikit-learn · pytest · YAML config ·
Streamlit (optional, later) for a simple signal dashboard.
