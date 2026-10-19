# ARVEN — Development roadmap

Status: **approved as target plan** (2026-09-28). News, macro, LLM, Telegram, dashboard and paper trading come only after the quantitative core (Stages 2–7) works. Durations are rough estimates for one developer.

**2026-10-01: Stage 7 (walk-forward evaluation) inserted between the ML meta-filter and the paper-signal loop.**
The former Stage 7 "Paper-signal loop" and everything after it are renumbered 8–11 (unchanged in scope/content,
only the number shifts) — this is a pure insertion, nothing about the paper-trading stage changed.
Each stage ends with: passing tests, updated `docs/current_state.md`, and user approval before the next stage.

| Stage | Name | Goal | Deliverables | Est. |
|---|---|---|---|---|
| 0 | Design | Agree on architecture | `CLAUDE.md`, `README.md`, `docs/*` | done (approved) |
| 1 | Foundations | Runnable, testable skeleton | `pyproject.toml`, `src/arven/core` (types, UTC/bar-time utils, config loader), `config/*.yaml`, pytest setup, `.gitignore` | done |
| 2 | Historical data | Reliable point-in-time market data | Binance bulk adapter (1m klines, funding, OI metrics), DuckDB schema, idempotent ingestion, quality checks + gap table, 1m→5m/15m/1h/4h resampling cross-checked vs native klines, CLI `arven ingest` | done: full backfill 2020-01 → 2026-07 verified (awaiting review) |
| 3 | Features | Causal features on all TFs | Feature registry, indicators, futures features, multi-TF as-of alignment, Parquet cache, **leakage test suite** | done: v1 (61 columns on the 1h grid) built, validated (403 tests; leakage suite incl. canaries; real-data spot check) and approved by the user |
| 4 | Backtester | Trustworthy evaluation engine | Clock, 1m execution model, fees/slippage/funding, portfolio, metrics, baselines (no-trade, buy&hold, random entry), hand-computed accounting tests, run logging | done: implemented, validated and approved (independent oracle on 300 seeds, ~30 hand-computed cases, leakage suite, real development-period baselines, deterministic run logging); `liquidation_includes_funding=true` confirmed as final |
| 5 | Regime + strategies + decision + risk | Complete rule-based pipeline | Rule-based regime detector, 3 independent baseline strategies, decision engine (regime-gated vote), risk engine rules, first full backtests on development period, per-regime analysis | done: implemented and validated (regime detector with hysteresis; trend/momentum, breakout, mean-reversion strategies; decision engine; 8-rule risk engine; 1346 tests incl. leakage/determinism/accounting-integration; real development-period run with per-regime breakdown); awaiting user review |
| 6 | ML meta-filter | Measurable ML contribution | Triple-barrier labels, purged/embargoed walk-forward, logistic baseline + LightGBM, calibration, SHAP, A/B vs strategies-only | done: implemented and validated (triple-barrier labels; purged/embargoed expanding-window walk-forward, 96h embargo; numpy logistic regression + LightGBM, ≤4-config grids; isotonic calibration; `MetaFilter` wired into `Stage5Pipeline` as an optional pass/veto stage; 1523 tests incl. 5 leakage-canary types, determinism, hand-computed labels; real development+validation data: 7572 candidates/7196 eligible, logistic +8.6% vs -20.3% Stage-5-only baseline with A/B controls); awaiting user review |
| 7 | Walk-forward evaluation (WFO) | Measure whether Stage 5/6 results hold up out-of-sample across time, not just on one development-period run | Causal (prior-folds-only) hyperparameter selection and calibration/threshold selection over the real 17-window expanding schedule (reused unchanged from Stage 6); per-window Stage-5-only / MetaFilter / shuffled-label / matched-rate-random backtests; sealed test period structurally unreachable | done: implemented and validated (36 new tests incl. causality/perturbation and sealed-test-isolation checks; full suite 1565 passed/13 skipped); real run on development+validation data — see `docs/current_state.md`'s "Stage 7" section for the full methodology and results |
| 8 | Paper-signal loop | Forward out-of-sample evidence | Incremental REST updates, bar-close scheduler, signal persistence, paper-trade tracker, CLI/Streamlit view | done: implemented and validated (new `BacktestPeriod.FORWARD`, REST-tail klines/funding into the existing tables, forward-period features built in memory, the real `Backtester`/`Stage5Pipeline` reused unmodified via `runs.execute_run`; `arven paper run`/`show`/`status`; CLI only, Streamlit deferred); real run on live data — see `docs/current_state.md`'s "Stage 8" section |
| 9 | Macro & news | Event awareness | **9a** (no LLM): macro calendar + risk blackout. **9b**: news ingestion + LLM structuring into fixed schema; evaluated forward-only / post-cutoff | 9a done: implemented and validated (real FOMC/CPI/NFP calendar sourced from federalreserve.gov/bls.gov, `config/macro_events.csv`, 228 rows 2020-2027; risk engine rule 2 — the last of the 8 rules — implemented as a symmetric veto window, additive/byte-identical-when-absent; 33 new tests, full suite 1638 passed/13 skipped); see `docs/current_state.md`'s "Stage 9a" section. **9b implemented, not yet real-API-tested**: news source is RSS (CoinDesk/CoinTelegraph — CryptoPanic's free tier was discontinued in early 2026, found while designing this), LLM provider is Anthropic (`claude-haiku-4-5-20251001`, thin stdlib-HTTP client, no SDK dependency); forward-only by construction (no `BacktestPeriod` concept in the package at all); 40 new tests against fakes, no real Anthropic call made yet (no API key available in-session) and not wired into any decision/risk/feature — see `docs/current_state.md`'s "Stage 9b" section |
| 10 | LLM explanations & chat | Usability | Explanation generator from structured signal payload; Q&A over stored data; Streamlit dashboard (deferred from Stage 8 - see Stage 8's own row) | done: implemented and validated (30 new tests, full suite 1708 passed/13 skipped; `src/arven/llm/explain.py`/`context.py`/`qa.py`, `arven explain`/`arven ask`; `src/arven/dashboard/` read-only presentation layer, `arven dashboard`, smoke-tested against this machine's real local paper/backtest data); **not yet real-API-tested** (same acknowledged gap as Stage 9b - no Anthropic key available in-session); see `docs/current_state.md`'s "Stage 10" section |
| 11 | Final evaluation & thesis | Honest results | Single sealed-test evaluation, robustness & cost stress tests, forward paper results, write-up | 2+ weeks |

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

## After the gold build-out: new features H1-H7 (planned, not approved)

2026-10-19: the owner picked seven "wow" features for people who do not know trading (news countdown, session globe,
"1000 universes", replay "time machine", Telegram signals as pictures, phone app (PWA), a no-code hypothesis lab).
The plan, in Russian, is `docs/FEATURES_PLAN.md`. It starts only after the gold evaluation (G5) is finished, one stage
at a time, each after the owner's approval.
