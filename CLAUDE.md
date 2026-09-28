# CLAUDE.md — ARVEN permanent project rules

ARVEN is an AI-assisted **decision-support** system for financial markets (university diploma project).
It outputs `LONG`, `SHORT` or `NO_TRADE` signals. MVP scope: **BTC/USDT perpetual futures only**,
timeframes 5m / 15m / 1h / 4h. It never executes real trades.

Read these before any work:
- `docs/current_state.md` — where the project stands right now (update it at the end of every work session)
- `docs/architecture.md` — the agreed design
- `docs/roadmap.md` — staged plan

## Working agreement with the user

- Do not write application code for a stage until the user has approved that stage.
- Do not install dependencies, add MCP servers, plugins, hooks, subagents or other tooling unless explicitly asked.
- Prefer simple, reliable designs. No microservices, message queues, Docker, Kubernetes or web frontends in the MVP.
- When a design decision in `docs/architecture.md` must change, update the doc in the same change and say why.
- Always update `docs/current_state.md` when finishing a piece of work.

## Non-negotiable engineering rules

1. **No look-ahead bias.** A value computed for decision time `t` may only use data whose
   `available_at <= t`. A bar is available only after it closes (`close_time`), never at `open_time`.
2. **No data leakage.** Normalisers, scalers, percentile ranks, thresholds, feature selection and
   hyperparameters are fitted only on training data (or on a trailing window ending at `t`).
   Never use `df.shift(-n)`, centered windows, `bfill`, or full-sample statistics inside feature code.
3. **Chronological splits only.** Train → validation → test in time order. Walk-forward with
   purging and embargo for ML. The final test period is sealed and evaluated as few times as possible;
   every evaluation of it is logged.
4. **Realistic costs.** Every backtest models taker/maker fees, slippage, and funding payments.
   Fills happen at the next bar's open (or later), never at the close of the signal bar.
   If stop-loss and take-profit are both touched within one bar and order is unknown, assume the worse outcome.
5. **NO_TRADE is a first-class outcome** and the default. Missing, stale or invalid data ⇒ `NO_TRADE`.
6. **Never claim or imply guaranteed profitability.** Report results with costs, drawdowns, number of
   trades, and comparison to baselines (buy-and-hold, no-trade, random entry with same holding time).
7. **Module separation.** Data, features, regime, strategies, ML, news, decision, risk and backtest are
   separate packages with explicit typed interfaces. Strategies do not know about risk; risk does not
   know which strategy fired; ML does not place trades.
8. **One code path for backtest and live.** Features, strategies, decision and risk logic must be the same
   code whether driven by the backtester or by the live/paper loop.
9. **LLMs are never the source of numeric trading calculations** (indicators, prices, sizes, stops, PnL,
   final decisions). LLMs may only: structure news/events into a fixed schema, write explanations
   from already-computed data, and power natural-language Q&A.
10. **Determinism and reproducibility.** Fixed random seeds; every backtest/model run records config,
    data range, feature version, code version (git commit) and results.
11. **Everything important is testable** and has tests — especially time alignment and leakage.
12. **No real order execution code** (no private API keys, no order endpoints) in the MVP.

## Code conventions

- Python 3.13 (existing `.venv`). Package lives in `src/arven/`. Tests in `tests/`.
- All timestamps are timezone-aware **UTC**; store as UTC milliseconds or `TIMESTAMP` UTC. Never local time.
- Type hints everywhere; dataclasses / pydantic models for cross-module contracts.
- Pure functions for feature/strategy/risk logic where possible (input frame → output), no hidden I/O.
- Config in YAML under `config/`; no magic numbers buried in code for strategy/risk parameters.
- Notebooks (if any) are for exploration only; nothing in `src/` imports from notebooks.
- Secrets only via environment variables / `.env` (git-ignored). Never commit keys.
- `data/` (raw downloads, database files, model artifacts) is git-ignored.

## Testing rules

- `pytest` for all tests. A change that touches feature, label, split or backtest logic must include a test.
- Leakage tests are mandatory for every feature: computing the feature on data truncated at `t`
  must give exactly the same value at `t` as computing it on the full dataset.
- Backtest engine must have hand-computed test cases (known trades → known PnL after fees/slippage/funding).
