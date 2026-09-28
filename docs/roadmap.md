# ARVEN — Development roadmap

Status: **approved as target plan** (2026-09-28). News, macro, LLM, Telegram, dashboard and paper trading come only after the quantitative core (Stages 2–6) works. Durations are rough estimates for one developer.
Each stage ends with: passing tests, updated `docs/current_state.md`, and user approval before the next stage.

| Stage | Name | Goal | Deliverables | Est. |
|---|---|---|---|---|
| 0 | Design | Agree on architecture | `CLAUDE.md`, `README.md`, `docs/*` | done (approved) |
| 1 | Foundations | Runnable, testable skeleton | `pyproject.toml`, `src/arven/core` (types, UTC/bar-time utils, config loader), `config/*.yaml`, pytest setup, `.gitignore` | done |
| 2 | Historical data | Reliable point-in-time market data | Binance bulk adapter (1m klines, funding, OI metrics), DuckDB schema, idempotent ingestion, quality checks + gap table, 1m→5m/15m/1h/4h resampling cross-checked vs native klines, CLI `arven ingest` | done: full backfill 2020-01 → 2026-07 verified (awaiting review) |
| 3 | Features | Causal features on all TFs | Feature registry, indicators, futures features, multi-TF as-of alignment, Parquet cache, **leakage test suite** | 1 week |
| 4 | Backtester | Trustworthy evaluation engine | Clock, 1m execution model, fees/slippage/funding, portfolio, metrics, baselines (no-trade, buy&hold, random entry), hand-computed accounting tests, run logging | 1–1.5 weeks |
| 5 | Regime + strategies + decision + risk | Complete rule-based pipeline | Rule-based regime detector, 3 independent baseline strategies, decision engine (regime-gated vote), risk engine rules, first full backtests on development period, per-regime analysis | 1.5–2 weeks |
| 6 | ML meta-filter | Measurable ML contribution | Triple-barrier labels, purged/embargoed walk-forward, logistic baseline + LightGBM, calibration, SHAP, A/B vs strategies-only | 1.5–2 weeks |
| 7 | Paper-signal loop | Forward out-of-sample evidence | Incremental REST updates, bar-close scheduler, signal persistence, paper-trade tracker, CLI/Streamlit view | 1 week |
| 8 | Macro & news | Event awareness | Macro calendar + risk blackout (first, no LLM); then news ingestion + LLM structuring into fixed schema; evaluated forward-only / post-cutoff | 1.5–2 weeks |
| 9 | LLM explanations & chat | Usability | Explanation generator from structured signal payload; Q&A over stored data | 1 week |
| 10 | Final evaluation & thesis | Honest results | Single sealed-test evaluation, robustness & cost stress tests, forward paper results, write-up | 2+ weeks |

## First month (Stages 1–4, start of 5)

Target at end of month 1: clean historical data, causal features with leakage tests, and a correct
backtester with baselines and one simple strategy — i.e. the *measurement instrument* is trustworthy
before anything tries to find an edge.

## Explicitly NOT built in the first month

- Real or simulated order placement via exchange APIs; private API keys
- WebSocket live streaming (REST polling is enough later)
- Liquidation data
- News, macro, sentiment, social media, any LLM integration
- Deep learning (LSTM, Transformers), reinforcement learning, AutoML
- Hyperparameter / strategy parameter optimisation searches
- Multi-asset or multi-exchange support
- Order-book / L2 microstructure
- Web frontend, REST API, Docker, microservices, message queues, cloud deployment
- Any use of the sealed test period
