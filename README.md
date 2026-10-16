# ARVEN

**ARVEN** is an AI-assisted decision-support system for financial markets, built as a university diploma project.
For BTC/USDT perpetual futures it produces `LONG`, `SHORT` or `NO_TRADE` signals with entry, stop, targets and
reasons. It sends them in real time to Telegram and shows them in a local web app.

> ARVEN does **not** execute trades and does **not** guarantee profitability. It is a research and decision-support
> tool with no order or account code. All reported performance is historical or paper-simulated, net of fees,
> slippage and funding. Every strategy is graded `EXPERIMENTAL`: none has shown a proven edge out of sample (see
> `docs/current_state.md`).

## What it does

- **Data:** Binance USDⓈ-M public data (1m klines → 5m/15m/1h/4h, funding, open interest), 2020 → now, in DuckDB,
  with point-in-time availability (no look-ahead).
- **Research core (Stages 0-10):**
  - causal features with leakage tests
  - regime detection, strategies, decision and risk engines
  - a 1m-resolution backtester with realistic costs
  - an ML meta-filter, walk-forward evaluation, a paper loop
  - news / macro data, and LLM explanations (LLMs never compute trading numbers)
- **Signal product:**
  - multi-timeframe event engine, five strategies (S4, S5, S6, S7, Crowded Shorts)
  - a live signal loop with Telegram alerts
  - a React web app (signals, charts, strategies with their full trade history, journal, lab)

## Quick start (Windows, existing `.venv`)

```
.venv\Scripts\python.exe -m pytest                 # test suite
.venv\Scripts\python.exe -m arven live run         # real-time signals (Ctrl+C to stop)
.venv\Scripts\python.exe -m arven live status      # strategies, last results, heartbeat
.venv\Scripts\python.exe -m arven web              # web app on http://127.0.0.1:8000 (build it first: cd web && npm run build)
.venv\Scripts\python.exe -m arven backup           # zip signals, runtime state and config into data\backups (--with-db: also the database)
```

- **Telegram:** put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS` in `.env`, then set `dry_run: false` in
  `config/telegram.yaml`.
- **Always-on (Task Scheduler), changing or adding strategies:** see [`docs/LIVE_SIGNALS.md`](docs/LIVE_SIGNALS.md).
  The tasks "ARVEN Live" and "ARVEN Web" run the signal process and the site without a window, and a watchdog
  restarts them. Strategies are switched and parameterised in `config/live.yaml`.
- **Backup:** market data can be downloaded again, but the forward signal record cannot. `arven backup` keeps the
  newest 10 archives in `data\backups`. Copy them off the laptop now and then. To restore one, unzip it into the
  project folder while the processes are stopped.
- **Troubleshooting:** `arven live heartbeat` shows whether the process is alive. If it says `STALE`, see
  `data\live\live_process.log` and `data\live\live.jsonl`. A sleeping laptop or a lost network gives `stale` ticks
  with no signals (NO_TRADE by design), and the process catches up by itself afterwards.

## Documentation

| Document | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Permanent project rules and development principles |
| [`docs/current_state.md`](docs/current_state.md) | Where the project stands, every result, the decisions log |
| [`docs/LIVE_SIGNALS.md`](docs/LIVE_SIGNALS.md) | The live signal loop: running it, Telegram, changing / adding strategies |
| [`docs/DEFENCE_DEMO.md`](docs/DEFENCE_DEMO.md) | 10-minute defence walkthrough (in Russian) |
| [`docs/RESULTS_FOR_THESIS.md`](docs/RESULTS_FOR_THESIS.md) | Every evaluation in one place, with sources (in Russian) |
| [`docs/DEPLOY_SERVER.md`](docs/DEPLOY_SERVER.md) | Running ARVEN 24/7 on a Linux VPS with systemd (in Russian) |
| [`docs/architecture.md`](docs/architecture.md) | System architecture, data model, backtesting, ML, risk, LLM usage |
| [`docs/roadmap.md`](docs/roadmap.md) | Staged development plan |
| [`docs/ARVEN_MASTER_PROMPT.md`](docs/ARVEN_MASTER_PROMPT.md) | The signal-product build-out plan |
| `docs/strategy_*.md` | Each strategy's pre-registered specification and results |

## Tech stack

Python 3.13 · numpy / pandas · DuckDB · scikit-learn / LightGBM · FastAPI · pytest · YAML config ·
React + TypeScript + Vite + Tailwind + lightweight-charts (web app) · Telegram Bot API (stdlib HTTP).
