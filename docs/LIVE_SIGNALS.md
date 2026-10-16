# ARVEN — live signals (`arven live`)

Real-time paper signals for BTC/USDT from every enabled strategy, on fresh Binance data, with Telegram alerts and the
web app. **Decision support only:** a signal is a suggestion with an entry, a stop and targets. ARVEN never places an
order and has no order or account code (CLAUDE.md rule 12). Every strategy is graded `EXPERIMENTAL`. The evaluations
behind them are in `docs/current_state.md`, and none of them shows a proven edge (CLAUDE.md rule 6).

## 1. What runs

One process, `arven live run` (`src/arven/live/loop.py`), wakes every 20 s (`poll_seconds`):

1. **New 15m close due?** (5 s after the close, `event_delay_seconds`.) If yes, run one **tick**
   (`src/arven/live/service.py`):
   - REST-update the database from Binance's public API: 1m klines, funding, and the 5-minute open-interest statistics
     (`include_open_interest`).
   - `through` = the last 15m close whose 1m bars are all stored. If the newest 1m bar is older than
     `max_data_age_seconds` (180 s), the data is **stale**. The tick then stops, no strategy is asked anything, and
     a Telegram alert is sent (CLAUDE.md rule 5: stale ⇒ NO_TRADE).
   - Every enabled strategy scans the decision times since its own cursor. New signals go to the signal store,
     `data/signals/<strategy id>/signals.jsonl`, and each is stored only once.
   - Every stored signal is replayed on the 1m data. Its new updates go to `updates.jsonl`: entry filled, TP hit, stop
     moved, cancelled (an unfilled limit withdrawn), closed with net R under the broker CFD cost profile.
   - New signals and updates that are less than `alert_recency_hours` (6 h) old are queued for Telegram. Older ones,
     found while catching up after downtime, are stored but not alerted.
   - `data/paper/strategies_summary.json` is rewritten for the web app and the bot.
2. **New hour?** Run the Stage 8 hourly `paper run` (`run_legacy_paper`). This keeps one process as the only
   database writer.
3. Drain the Telegram outbox, answer bot commands, queue the daily summary (00 UTC, for the day that ended) and
   system alerts (start, stale data, three failed ticks in a row).
4. Write the heartbeat `data/live/heartbeat.json`, the state `data/live/state.json` and the log
   `data/live/live.jsonl`.

A tick takes about 1.5 minutes on this laptop. Most of that is the S7 detector, which runs over all 15m bars since
2020 so that it sees exactly what the research saw. A signal therefore arrives a minute or two after its bar closes.

**Restart-safe.** Cursors (`data/paper/strategies_cursor.json`) and loop state are persisted. After a restart or a
sleep, the next tick catches up on every missed close in order, and nothing is duplicated. A failing strategy keeps
its cursor and is retried next tick; the others carry on.

## 2. The strategies and how a signal looks

| id | kind | entry | exit |
|---|---|---|---|
| `s4_impulse_retest` | S4 provider | market at the 15m close | stop / TP1-TP3 ladder (50/30/20) |
| `s5_squeeze_breakout` | S5 provider | market | stop / ladder |
| `s6_trend_pullback` | S6 provider | market | stop / ladder |
| `s7_trend_break_fib` | S7 detector + simulator | **limit** at fib 0.5 (E3), valid until the setup's expiry | stop S1 (fib 0.1) / TP1 fib 1.0, TP2 resistance in 1.272-1.618, TP3 fib 2.0 |
| `crowded_shorts` | funding + OI rule | market long | stop 3 % / time: 24 h after the last qualifying signal (no TP) |

Every live adapter (`src/arven/live/strategies.py`) calls the same code as the research (CLAUDE.md rule 8). This was
checked on the forward period 2026-07-01 → 2026-10-11:

- All 21 S7 research trades were reproduced with bit-identical net R.
- All 3 Crowded Shorts trades were reproduced with bit-identical net R.

Live S7 shows 5 more closed trades than the research table. The research applies "one trade at a time", while live
tracks every signal on its own, as for S4-S6.

A signal (`EngineSignal`) carries: side, entry price and `entry_type` (`market` or `limit` with `valid_until_ms`),
stop, TP ladder (price, R, fraction), risk 1 % of equity, the reasons, and the versions (feature version, a hash of
the strategy's params, git commit). Statuses in the web app: *waiting for entry* (limit not filled), *open*,
*partly closed*, *closed*, *cancelled*.

## 3. Changing a strategy, adding a strategy

Everything the live loop runs is listed in **`config/live.yaml`**.

- **Switch a strategy off/on:** set `enabled: false` / `true`. It applies from the next process start.
- **Change S7 or Crowded Shorts parameters:** edit `params` and **bump `version`** (e.g. `v1` → `v2`). Every signal
  carries the version and a hash of the params, so old and new signals are never confused. Also decide whether
  the old history should stay under the same `id`. If not, give the changed strategy a new `id` (e.g.
  `s7_trend_break_fib_v2`), which starts a fresh signal store and cursor. S7 accepts the keys of the S7 study
  (`tf`, `min_touches`, `impulse`, `freeze_pullback`, `entry`, `stop`, `breakeven_after_tp1`, `min_tp1_r`,
  `management`, ...). An unknown key is an error at start-up, not a silent default. Crowded Shorts accepts
  `fund_z_max`, `oi_z_min`, `hold_hours`, `stop_fraction`.
- **Change S4/S5/S6:** their rules are pre-registered constants in `src/arven/engine/strategy_s4.py` / `_s5` / `_s6`
  (and the adapters in `src/arven/backtest/strategy_s*_provider.py`). Change them there and bump `STRATEGY_VERSION`.
- **Add a new strategy:**
  1. Write the rules as pure functions in `src/arven/engine/` and, if fills need simulating, the execution in
     `src/arven/backtest/`. Add leakage tests (CLAUDE.md rule 2) and evaluate it on development/validation first.
  2. Write a class with `strategy_id`, `title`, `scan(ctx, after_ms, through_ms, stored)` and `resolve(ctx, signal)`
     (the protocol `LiveStrategy` in `src/arven/live/base.py`; the three existing adapters are the templates).
     `ctx` gives bars of every timeframe, the 1m market, the cost profile, and the Stage 3 features on demand.
  3. Register its `kind` in `KINDS` in `src/arven/live/registry.py` (and in `NEEDS_FEATURES` if it reads features).
  4. Add an entry to `config/live.yaml` and restart the process.

  Nothing else changes: the signal store, Telegram, the web app and the summary pick it up by its id.

Every change is still research. A new or changed strategy starts `EXPERIMENTAL`, and only data it has not been tuned
on (forward) says anything about it.

## 4. Running it

**Foreground (try it):**

```
.venv\Scripts\python.exe -m arven live run
```

Stop it with Ctrl+C. Other commands:

- `arven live tick`: one pass and exit.
- `arven live status`: enabled strategies, last summary, heartbeat.
- `arven live heartbeat`: exits non-zero if the process is stale or in error.

**Always on (Windows Task Scheduler).** The task runs the process **without a window** (`pythonw`, output in
`data\live\live_process.log`), so it cannot be closed by accident. A second trigger re-checks every 5 minutes and
starts the process if it is not running. A second copy exits at once, because the first holds the lock
`data\live\live.lock`. The task replaces the hourly "ARVEN Paper Run" task: the live process does that hourly run
itself, and there must be only one database writer.

```powershell
Disable-ScheduledTask -TaskName "ARVEN Paper Run"
$repo = "C:\Users\Victus\arven"
$action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" `
    -Argument "-m arven live run --stop-file data\live\live.stop --log-file data\live\live_process.log" -WorkingDirectory $repo
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "ARVEN Live" -Action $action -Trigger @($t1, $t2) -Settings $settings
Start-ScheduledTask -TaskName "ARVEN Live"
```

Why windowless: the first version ran `run_live.bat` in a console window. On 2026-10-14 that window was closed, and
the task ended with `0xC000013A` (Ctrl+C / window closed). Windows does not count that as a failure, so the task was
not restarted, and nothing ran for two days. `scripts\run_live.bat` is still there for a manual run in a console.

- **Stop:** create `data\live\live.stop`. The process exits within a second. While the file exists, the watchdog's
  restarts exit immediately.
- **Start again:** delete `data\live\live.stop`. The watchdog starts the process within 5 minutes, or run
  `Start-ScheduledTask -TaskName "ARVEN Live"` to start it at once.
- **Remove for good:** `Unregister-ScheduledTask -TaskName "ARVEN Live"`, then `Enable-ScheduledTask -TaskName "ARVEN
  Paper Run"` if you want the hourly run back.
- **Power:** a sleeping laptop is not 24/7 (`docs/RUNTIME_OPERATIONS.md`, "Power settings"). After a sleep, the
  process catches up automatically.
- **The web app** (`arven web`) reads the same files and the database read-only. During the few seconds a tick
  writes, an API call may answer "database busy, retrying".

## 5. Telegram

Telegram is off until you give it a bot and a chat:

1. Create a bot with @BotFather and copy its token. Send your bot any message, then find your chat id (for example
   with @userinfobot).
2. Put both in `.env` in the project folder. The file is git-ignored, so it is never committed:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_IDS=123456789
   ```
3. `arven telegram test` sends one real test message.
4. In `config/telegram.yaml`, set `dry_run: false`. While it is `true`, alerts are queued and marked as sent, but
   nothing leaves the machine.
5. Restart `arven live run`.

The startup line shows how many chats are configured, whether the token is set, and whether it is in dry run.

You get:

- **New signals:** side, entry (and whether it is a limit), stop, TPs with R, risk, reasons.
- **Updates:** filled, TP hit, stop moved, cancelled, closed.
- **A daily summary.**
- **System alerts:** started, data stale, repeated errors.

Bot commands: `/status`, `/signals`, `/history`, `/strategies`, `/pause`, `/resume`, `/help`. Only the chats in
`TELEGRAM_CHAT_IDS` get answers.

## 6. Data notes

- **Open interest** comes from Binance's public `futures/data/*` endpoints (5-minute statistics, latest 30 days only).
  Compared with the bulk `metrics` files on 500 overlapping rows, the REST open interest is identical. The ratios
  match to their 4 decimals, and the REST timestamps are 5 minutes later than the bulk `create_time` (taker ratio:
  same time). Rows are stored under the bulk convention, so history and live data form one series. Bulk rows are
  never overwritten by REST rows.
- If the process is down for more than ~29 days, the open-interest gap cannot be filled from REST. `oi_z` is then NaN
  until its trailing 30-day window is again at least 90 % covered (the feature's own coverage rule), and Crowded Shorts gives no signals in that
  time (missing data ⇒ no trade). The daily bulk files can fill such a gap (`arven ingest`).
