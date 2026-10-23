# ARVEN — Current state

_Last updated: 2026-10-23 (H3 1000 universes computed for both markets; H4 time machine with 10 scenarios; earlier: H1 News page: countdown, past-release moves, Telegram reminder - live restart pending; earlier 2026-10-22: H2 Sessions page: globe, market and centre status, activity heat map; trade charts show the whole trade; gold build-out G1-G5 closed - small leftovers listed in the gold section; heartbeat "stale" this morning was the laptop asleep, not a bug; earlier 2026-10-21: gold (XAUUSD): history downloaded and checked, holiday calendar fixed, full research run done - docs/RESULTS_GOLD.md; live enable awaits the owner; earlier 2026-10-19: G1-G4 code done - see "Gold (XAUUSD)" below; new-feature plan H1-H7 in docs/FEATURES_PLAN.md; earlier: 2026-10-16 improvement pass: S7 detector ~5x faster with identical results, forward review rule, weekly report, daily backup and retention, server deployment files, Telegram live; earlier: live signal loop: `arven live run` runs all five strategies in real time, configurable in config/live.yaml, open interest REST-tailed, Telegram-ready; earlier: every strategy's trades on the Strategies page; S7 trade-management study - no variant helps, S7 forward -7.3 R; earlier: Crowded Shorts sealed test run once: CONFIRMED by the pre-registered rule but weak - CFD +1.68 R / 25 trades, PF 1.27; earlier: web redesign v2: grouped sidebar/drawer/Ctrl+K, chart fit/full-screen/OHLC legend, S7 trade verdicts + SMC zones on the trades page; SMC-zone breakdown of S7 trades; earlier: S7 trades page + $1000 account replay + cost check; owner: no more new strategies; earlier: S7 validation run once: CFD -3.05 R / 102 trades, inside the random-entry control - the development result did not replicate, S7 EXPERIMENTAL; earlier: S7 evaluation stage, development selection CFD +47.6 R / 167 trades in-sample; earlier: S7 owner check round 2 done, variants 12/13 added, labelling stopped; earlier: S7 detector v2 from the owner's round-1 check of 100 setups; earlier: Signal-product build-out Phase 8 complete (8a API, 8b React app, 8c browser tests/Lighthouse); earlier: Strategies S5 and S6 and an ML signal filter (no value) added and evaluated; forward evaluation of S4/S5/S6 wired (first 14 weeks negative); Phase 7b, part 2c: exit-variant study + CFD cost profile; part 2 + validation/forward check: S4 validation +0.7 % (40 trades), forward 4 trades; part 2: S4 evaluated on development - negative, -20.5 %, 108 trades, 14.8 % win rate; earlier Phase 7b, part 1: S4's SignalProvider adapter wired end to end and hand-verified; the development backtest/WFO/baselines/stress/per-regime/forward-paper evaluation itself is still to come)_

## Gold (XAUUSD) build-out - DONE, G1-G5 closed 2026-10-22 (branch `feat/gold-xauusd`, started 2026-10-18)

**Closed 2026-10-22 (owner's request).** G1 data, G2 engine, G3 costs, G4 live/web and G5 the full gold evaluation
(`docs/RESULTS_GOLD.md`, items 4-7 below) are finished; gold paper signals run live next to BTC. Nothing in the gold
results is evidence of an edge: S4 is the best lead, S7-SMC is being checked forward (item 11). Leftovers, none
blocking: a second spread check near the 00:00 server rollover (owner, in MT5); a re-run of the 2 phone Playwright
tests that once timed out (the last full run was 72 passed). The new-feature plan H1-H7 (`docs/FEATURES_PLAN.md`)
may start now, one stage at a time after the owner's "yes"; H5 is already done.

**Live monitoring note (2026-10-22).** The heartbeat (`data/live/heartbeat.json`) stood at 07:45 UTC while the log
already showed ticks at 08:32 - not a bug. The Windows event log shows the lid closed at 07:44:53 UTC and the laptop
asleep until 08:31 UTC; the loop writes the heartbeat after each poll, the poll in flight was frozen with the machine
and finished on wake. Before that, 03:59-07:44 UTC, every Binance request failed with `getaddrinfo failed` (no network
on the laptop); the loop marked the data stale (NO_TRADE) as designed and caught up by itself. Live signals on a laptop
stop whenever it sleeps or is offline - the lasting fix is the server (`docs/DEPLOY_SERVER.md`) or a "do not sleep on
mains power" setting.

Owner request: add gold with every current strategy, working exactly like BTC, then the full analysis as for BTC
(especially S7: stops, FVG, management, zones...). Owner's choices: history from Dukascopy + live from Binance
XAUUSDT; signals only while the CME metals market is open; spread "typical value" (set from the data). Design:
`docs/architecture.md` section 18.

**Done and committed (tests: 2401+ passing, BTC results and config hash unchanged):**
- G1 data: `arven.core.sessions` (CME metals calendar, verified on the feed), Dukascopy adapter + resumable
  downloader + ingest (`arven --instrument XAUUSD duka download|ingest|closures`), session-aware ingestion
  (Binance bulk/REST), resample, quality, native cross-check; instruments `config/instruments/XAUUSD.yaml`,
  `XAUUSDT.yaml`.
- G2 engine: session bar grid, staleness, decision masks, 1m gaps, trading time (S4 line, S6 cooldown), S7 resistance
  window in bars, FeatureView on a session hourly grid, funding/trade-flow features optional; leakage-tested.
- G3 costs: `config/costs_cfd_justmarkets_xauusd.yaml` (spread placeholder 1 bps/side - **to be set from the
  Dukascopy spread**, `gold_study.py crosscheck`); swap reported as a sensitivity.
- G4 live/web: `config/live.yaml` `markets` (gold **enabled: false** until data is verified), per-market loop state,
  Telegram labels/commands/reports, backups of `data/markets/`, web BTC/Gold switch (`market=` on the API). Playwright:
  70/72 passed on the last full run; 2 phone tests timed out while memory was short - **re-run when memory allows**.

**Done 2026-10-21:** the Dukascopy download (2020-01-01 -> 2026-10-19) is complete after five resumed passes (the
feed answered 503 / timeouts for ~40 % of requests): 4 966 of 4 966 files (BID 2 483, ASK 2 483), 0 failed,
0 not available, no `.part` or empty files, 66 MB. Logs `data/tmp/duka_download*.log`. Resume command for later days:
`python -m arven --instrument XAUUSD duka download --start 2020-01-01 --end <today>`. Background shells inside the
Claude session get stopped when memory is low (7.2 GB machine) - launch long jobs as separate processes.

**Next, in order:**
1. ~~download complete -> `gold_closures.py --write` -> commit the CSV~~ **done 2026-10-21**: 87 rows (71 observed
   2020-01 -> 2026-09, 16 projected through 2027). One UNMATCHED run left out as a feed gap (2024-10-09 23:06 -> 00:11
   UTC, 65 min after the daily reopen). Fix in the script first (test `tests/unit/test_gold_closures.py`): a
   Friday-to-Monday closure was labelled with an eve that fell on the Sunday (2023), and Christmas observed on the 24th
   (2021) was overwritten by "Christmas Eve" - projected, those patterns would have closed ordinary trading days
   22-24 and 29-31 December 2026/2027. Christmas Eve / New Year's Eve now have no own pattern (their early closes are
   part of the Christmas / New Year runs). Two observed ends run a few minutes past the 23:00 reopen (2021-11-25 23:18,
   2025-12-25 23:04: quiet feed minutes) - kept, harmless (a few NO_TRADE minutes);
2. ~~`duka ingest`, `resample`, `quality`, then Binance XAUUSDT~~ **done 2026-10-21** (no DB collision seen):
   - XAUUSD (Dukascopy, download topped up to 2026-10-20): 2 485 days ingested, 2 413 193 1m rows in session
     (out-of-session minutes dropped), 2020-01-01 23:00 -> 2026-10-20 23:59 UTC; `quality` 2020-01-01..2026-10-21:
     **all PASS, no warnings**.
   - XAUUSDT (Binance, listed 2025-12-11 08:05 UTC): 354 files ingested, 11 not available (before the listing);
     `quality`: 1m rows = expected minus the pre-listing minutes exactly (no gap after the listing); funding through
     2026-09-30 (October's monthly file not published yet); open interest has 237 small 5m gaps (unused for gold).
   - `crosscheck` XAUUSDT **FAIL, understood**: 554 of 60 655 5m bars (and 179 15m / 44 1h / 6 4h) differ from
     Binance's native klines, **only between 2025-12-11 and 2026-01-15** (the illiquid first weeks after the listing),
     always in the *open* (high/low only where that open was the extreme); close, volume, quote/taker volumes and trade
     counts match exactly everywhere. A Binance data quirk in the native klines, not a resampling error; nothing
     changed. Gold research uses the Dukascopy history; XAUUSDT comparisons are cleanest from 2026-01-16;
3. ~~crosscheck -> spread~~ **done 2026-10-21**: XAUUSDT - Dukascopy basis median +$2.6 (+5.9 bps), return corr
   1h 0.991; Dukascopy median spread 2.19 ... 1.51 bps (2020 ... 2026) -> `fixed_bps` kept at 1.0 per side (2.0 round
   trip, conservative), the reasoning now in `config/costs_cfd_justmarkets_xauusd.yaml` (comment only);
4. ~~features + full gold research~~ **done 2026-10-21** (19 steps, `data/tmp/gold_research.ps1`, log
   `data/tmp/gold_research.log`; sealed test never requested): results and conclusions in **`docs/RESULTS_GOLD.md`**.
   Short version (CFD, R, dev / val / fwd): S4 +16.6 / +6.3 / +1.2 (only one positive on both main periods, but CIs
   cross 0 and x4 costs turn it negative - a lead); S5 -11.3 / +21.6 / +1.7; S6 -5.5 / +6.5 / -1.9; S7 (BTC config)
   -18.2 / -25.4 / +2.9; S7 re-selected on gold dev +19.8 -> val -19.7 / fwd -0.5 (the method does not replicate,
   as on BTC); S1-S3 pipeline -15.6 % / +4.1 % (stress -19.8 % / -16.2 %), not better than random entry. The pipeline's
   buy-and-hold starts at feat_ready (2020-08-17, $1941), hence -1.1 % on development;
5. **S7 full grid done 2026-10-21** (docs/RESULTS_GOLD.md 5a; rule pre-registered in `6cbca9d`): 144 configs
   (touches 3/2 x impulse fvg/none x stops F0/F01/F02/F03/S2/C0 x zones all/fvg/ifvg/ob/any/2+ SMC); none positive on
   validation under x4 costs; the pick (t2|none|F0|2plus_smc) dev +20.3 R -> val -2.5 R. Only lead: "2+ SMC zone types
   in the entry zone" (6 of the 9 dev+val-positive configs, all without the FVG impulse) - found after seeing
   validation, so it needs BTC as one pre-registered hypothesis (owner's call). **BTC check run once 2026-10-21**
   (`scripts/research/s7_smc_btc.py`, rule committed in `8be9268`, logged in `data/s7_study/evaluations.log`): no FVG
   impulse + 2+ SMC zone types, stop fib 0.1 - dev 96 trades +31.1 R, val 48 +8.5 R (mean +0.177 vs random p95 +0.212),
   x4 +11.2 / +2.8 R, forward 7 -1.3 R -> **verdict "not supported"** (just below the random-control bar). Strongest S7
   lead so far; only a forward check of the unchanged rule can settle it;
6. **Finished 2026-10-21 (owner: "start with point 1"):**
   - gold live **on** (`config/live.yaml` market XAUUSDT `enabled: true`, paper only). Live process stopped with the
     stop file, `arven --instrument XAUUSDT live tick` back-filled the forward period (S4 5 / S5 14 / S6 128 / S7 20
     signals; live S7 gold -1.26 R vs research +2.9 R - different feeds, XAUUSDT vs Dukascopy), restarted via the
     "ARVEN Live" task; its start line lists the Gold strategies;
   - `scripts/strategy_trades_export.py --instrument XAUUSD` -> `data/markets/XAUUSD/strategy_trades/` (gold CFD
     profile, 1 oz lots as `size`/`size_unit`, research signals of all periods, S7 live config, no Crowded Shorts).
     Totals equal docs/RESULTS_GOLD.md exactly; BTC development/validation output byte-identical to before;
   - the "ARVEN Web" process (running since 2026-10-16, older than the BTC/Gold switch) restarted and `web/dist`
     rebuilt: `/api/strategy_trades?market=gold` serves the gold trades;
   - Playwright: one flaky failure ("S7 check" key right after a save) traced to a real UI race - the key handler was
     swapped in a passive effect after the next setup was painted; now `useLayoutEffect`. Full e2e **72 passed**,
     4 skipped (screenshots);
   - `feat/gold-xauusd` fast-forwarded into `main` and pushed.
7. **Gold spread verified and everything recomputed (2026-10-21 evening).** Owner's MT5 (`XAUUSD.m`): Bid 4358.75 /
   Ask 4359.01 = $0.26 = 0.60 bps round trip -> `fixed_bps` 1.0 -> **0.4** per side (~35 % headroom; x4 stress ~$1.40).
   Signal recording is cost-independent (forward re-record byte-identical), so `all`, `money`, `s7grid`, `s7rules`,
   `s7select`, `s7full`, `s7full_select`, the S1-S3 pipeline/baselines and the gold web export were re-run
   (`data/tmp/gold_spread.ps1`; old results in `data/tmp/gold_before_spread/`); the live process restarted with the new
   profile. docs/RESULTS_GOLD.md rewritten. Headline: S4 +23.0 / +9.1 / +1.6 R and **still positive under x4**
   (+10.7 / +3.7 / +0.8) - the best gold candidate, small samples; S7 (live config) -11.0 / -19.6 / +3.1; S7 lead
   "no FVG impulse + 2+ SMC zones" +3.3 / +7.3 (x4 -0.2 / +3.6); S1-S3 pipeline -10.7 % / +9.8 %.
   Still worth a second spread check near the 00:00 server rollover.
8. **No fake "Confidence" (2026-10-22).** New-signal alerts showed `Confidence: 50%` (a placeholder for S7 / Crowded
   Shorts, an untested setup heuristic for S4-S6). Now: `Risk: 1.00% of equity (fixed rule, the same for every
   signal)`, `Quality: no validated per-signal estimate` and the strategy's paper record
   (`Record (paper since <forward start>): N closed, win W%, net R`, the alerted signal excluded;
   `arven.live.service.track_record`). New-signal alerts are formatted after the strategy's outcomes are resolved; the
   alert order is unchanged (its new signals, then its updates). Web "Signals" page: the confidence row became the same
   "no validated estimate" note. `confidence` stays in the signal record. Tests: telegram/live 2 new, full suite 2419
   passed, e2e 72 passed. Live process restarted.
9. **H5: signals as pictures in Telegram (2026-10-22, owner: "do H5").** `arven.telegram.chart` draws a PNG with
   Pillow (already installed with streamlit, now declared `pillow>=10.1`; no matplotlib): 15m candles closed by the
   signal / update time only (`candles_until`; a test proves later bars never change the picture), entry / stop / TP
   lines with the alert text's `.2f` prices (`level_labels`; tested against the text), risk / reward areas, the event
   mark ("Closed: STOP"), refused on stale data (> 1 day between the newest candle and the signal). `live/service.py`
   draws one picture per queued alert into `data/telegram/charts/` (`telegram.outbox.save_chart`, atomic write); the
   sender (`telegram.runs`) uses `sendPhoto` with the text as caption and falls back to `sendMessage` if the picture
   fails or the text exceeds 1024 characters. Switch: `config/live.yaml` `telegram.charts`. No DB schema change.
   Tests: `tests/telegram/test_chart.py` (13) + 2 in `tests/live/test_live_service.py`; full suite 2434 passed.
   **S7 drawing added (same day, owner: "add the S7 line and zone"):** `ChartOverlay` (lines, points, levels, zone)
   in `telegram/chart.py`; `S7Strategy.overlay(ctx, signal)` returns the setup behind a signal from the tick's own
   setup cache (trend line from its first anchor to the break, touches on highs / lows, fib 0 / 0.5 / 1, entry zone
   from fib 1 on) - nothing is stored and the signal record / `signal_id` are untouched, so update pictures of older
   signals get it too. The window widens back to the line's start (`candles_until(since_ms=...)`, cap 240 candles).
   Tests: overlay mapping (long and short, fake setup) + clipping, widening, no look-ahead with an overlay.
   Owner's check: one stored gold S7 signal sent as a TEST picture to both chats - arrived, works.
10. **Telegram in Russian (2026-10-22, owner: "signals in Russian").** `config/live.yaml` `telegram.language: ru`
   (`LiveTelegramConfig.language`, default `en`). `arven.telegram.ru`: Russian new-signal text, readable update details
   ("TP1: закрыто 50 % позиции по 4135.12", "Позиция закрыта по стопу", cancel reasons in words), daily summary, weekly
   report, system alerts, bot replies (`CommandContext.lang`) and the picture's words. Stored reasons / details stay
   English (they are hashed) and are translated by fixed patterns - checked on every stored record: 426 signals and
   854 updates, 0 untranslated; the longest Russian alert is 878 characters (caption limit 1024). The English wording
   is unchanged (all old tests pass as they were). Cyrillic on the picture needs a system font (`chart.cyrillic_font`:
   DejaVu / Arial / Segoe UI / Liberation; on Linux `fonts-dejavu-core`), otherwise the picture falls back to English.
   Tests: `tests/telegram/test_ru.py` (30) + 1 live-tick test.
11. **S7-SMC as a frozen paper forward check (2026-10-22, owner: "start with point 1").** New live strategy `s7_smc`
   (BTC and gold, `config/live.yaml`): the live S7 with exactly the two changes pre-registered in
   `scripts/research/s7_smc_btc.py` (`8be9268`) - `impulse: none` and the new S7 setup filter `min_smc_types: 2`
   (`arven.live.strategies.smc_types`: distinct FVG / iFVG / order-block zones overlapping the entry zone; default 0 =
   the old S7 unchanged). A test pins the params to the live S7's except those two, on every market. Parity on real
   BTC data: the live strategy finds exactly the research check's 9 forward setups. Clean, never-seen evidence starts
   2026-10-22 (July-October forward was already looked at: 7 trades, -1.3 R) - judge it on signals from that date on,
   with the forward review rule (30 closed signals). Expected pace (from the history): BTC ~0.6 setups a week (9 in
   16 weeks), gold ~0.3 trades a week (validation 24 in 18 months) - 30 closed signals take roughly half a year or more.
12. **Trade charts show the whole trade (2026-10-22, owner: "the chart does not load fully").** The Strategies page's
   trade candles (`scripts/strategy_trades_export.py candles`) were cut by calendar hours (48 h before the entry): a gold
   trade on a Monday got ~9 bars, the weekend being closed. Now 48 bars before / 24 after, counted in bars (identical on
   BTC's unbroken grid: checked on all 1008 stored BTC trades). Trades longer than 500 bars (S6: 19 BTC, 9 gold) used
   to lose their entry to the cap; now k consecutive 1h bars are merged into one candle so the whole trade fits. Both
   exports re-run: totals, R, $ and every non-candle field unchanged (dev/val/test compared with the old files, kept in
   `data/tmp/{btc,gold}_trades_before_window/`). `CandleChart` fixes both edges when it has no `onNeedOlder` (trade
   charts), so zooming out no longer shows empty space; the Charts/Signals pages are unchanged. `web/dist` rebuilt.
   e2e (signals/charts/strategies/S7 subset): 29 passed, 2 desktop tests failed once under load and passed on re-run.
13. **H2: the Sessions page (2026-10-22, owner: "add the globe feature").** `#/sessions` (sidebar group Market):
   - a dotted globe on a canvas (`web/src/Globe.tsx`, no 3D library): land from Natural Earth 1:110m (public domain)
     packed by `scripts/web_land_mask.py` into `web/src/landmask.ts` (18 330 dots, 5 288 on land, 2.3 kB); day / night
     from the sun's position (display-only approximation); Sydney / Tokyo / London / New York glow while inside their
     conventional local working hours (Mon-Fri 07-16 / 09-18 / 08-17 / 08-17, DST-exact via zoneinfo) - context only,
     never used by a signal; turns by itself (still with reduced motion), can be dragged, draws nothing off screen;
   - market status from the real session calendar (`arven.web.sessions.market_state`: always open / trading / daily
     pause / weekend / holiday with its name), live countdown to the next change, next holiday or early close from
     `config/sessions/cme_metals_closures.csv`;
   - activity heat map: mean `(high - low) / open` of completed 1h bars by weekday and hour over the last 365 days
     (`activity_grid`; only bars closed before now; the feed with more bars - gold uses the Dukascopy history), shown in
     the viewer's time or UTC; cached for an hour in the web process (the database is often busy with the live tick).
     Described as history of how much the price moved, not a direction or a forecast.
   - API `/api/sessions`, `/api/activity?market=&days=`. Tests: `tests/web/test_web_sessions.py` (11: Friday close / Sunday
     reopen in winter, summer halt, a holiday merged with the halt, London BST, New York weekend, Sydney after its DST,
     Tokyo, grid buckets, unclosed bars ignored, empty grid) + 2 API tests; full suite 2485 passed; e2e page list includes
     `sessions` (home/overview/sessions subset: 16 passed).
   - Checked on the real data (a separate server on port 8766): London closes 16:00 UTC (BST), gold's halt 21:00 UTC,
     gold's Saturday cells empty, next holiday Thanksgiving 2026-11-26; desktop / phone / light screenshots, no console
     errors, no horizontal scroll. The "ARVEN Web" process (port 8000) was then restarted (only its two processes, the
     live process untouched) and serves both endpoints.
14. **S7 trades page for gold (2026-10-22, owner: "it does not work" - the page was empty on Gold).**
   `scripts/s7_trades_export.py --instrument XAUUSD` writes `data/markets/XAUUSD/s7_study/trades_<period>.json`: gold
   history, gold's CFD profile, the live S7 configuration (as the Strategies page and docs/RESULTS_GOLD.md), 1 oz lots
   (`size` / `size_unit`). Totals equal the Strategies page exactly (development 144 trades, $1000 -> $929.88;
   validation 64, $816.48). BTC output path and content unchanged. The page's subtitle names the gold rules on Gold.
15. **S7 check for gold + its chart scrolls again (2026-10-22, owner: "S7 check works only on BTC, the chart looks bad
   and does not scroll").** The scroll was a regression of item 12: fixed chart edges applied to every chart without
   `onNeedOlder`, including the S7 check (no right offset, no panning). Now an explicit `CandleChart fixEdges` prop, set
   only by the trade charts (`TradesViewer`). Gold: `scripts/s7_review_export.py --instrument XAUUSD [tf] [n]` -> 
   `data/markets/XAUUSD/s7_review/setups_<tf>.json` (gold history on its session grid, today's `S7Params()` defaults,
   seed 7): 15m 30 of 487, 1h 40 of 132, 4h all 34. `/api/s7/review` and `/api/s7/labels` (GET/POST) take `market=`;
   gold's labels are stored under `data/markets/XAUUSD/s7_review/`, BTC's stay in `data/s7_review/` (test
   `test_s7_review_of_gold_has_its_own_setups_and_labels`). Web restarted (web processes only). e2e S7 / charts /
   strategies subset: 23 passed.
16. **H1: the News page and event reminders (2026-10-23, owner: "start H1").** `#/events` (sidebar group Market):
   a live countdown to the next FOMC / CPI / NFP release, the next ones, and for the chosen market (BTC / Gold) how the
   price moved after past releases. `arven.event_moves` (pure, on stored 15m bars): per release and horizon (15 min,
   1 h, 4 h) the range `(high - low) / price at the release` and `|move|`, both in %, and a baseline - the median
   range of the same UTC window on up to 20 earlier event-free weekdays. Only fully closed windows count (no
   look-ahead, tested: truncating the bars at `now` gives the same rows); a window with a missing bar is left out; on
   gold a horizon is trading time (the daily halt skipped, a weekend / holiday window left out). Real numbers (first
   hour, median vs ordinary day): BTC FOMC 2.05 % vs 0.77 %, CPI 1.53 vs 0.81, NFP 1.40 vs 0.83; gold FOMC 0.96 vs
   0.17, CPI 0.86 vs 0.41, NFP 0.95 vs 0.40 (55 / 80 / 80 and 54 / 79 / 77 releases). API `/api/events?market=`
   (cached an hour). Telegram: one reminder `telegram.event_reminder_minutes` (60) before each release with the
   first-hour numbers for BTC and gold (`LoopDeps.queue_event_reminder`, remembered in `state.extra["event_reminders"]`,
   the outbox de-duplicates too). **The calendar ends: NFP 2026-11-06, CPI 2026-12-10, FOMC 2027-12-08** - later
   CPI / NFP dates must be added to `config/macro_events.csv` from bls.gov (not invented). Tests:
   `tests/unit/test_event_moves.py` (7), loop reminder, ru/en text, API; full suite 2496 passed; e2e events / sessions /
   home 14 passed. Web restarted (web processes only). **The reminder needs a restart of the live process** (not done:
   the owner's call).
17. **H3: "1000 universes" (2026-10-23).** `arven.backtest.universes`: a random trader copies each exported trade's
   side, stop distance (%) and TP ladder in R (50 / 30 / 20 %), enters at a random 1m bar of the same period (leaving
   30 days to resolve), same tracker and CFD costs, same $1000 account; 1000 per strategy and period, seeded
   (`[7, crc32(symbol|strategy|period)]`). Verdict: `too_few` under 30 trades, `skill_candidate` at >= 95th percentile
   of the random final balances, else `luck`. `scripts/research/universes.py` (resumable, waits for the database;
   seed / commit / rules in every file; the strategy's own curve recomputed and checked against the export) ->
   `data/research/universes/`, `data/markets/XAUUSD/research/universes/`; `/api/universes`; page `#/universes` (fan,
   verdict, numbers, histogram; a warning on the training period, where settings were chosen). Crowded Shorts is
   left out (time exit). Run as a separate hidden process (`data/tmp/universes_run.ps1`, ~6 h with the laptop asleep
   part of it). Results (strategy final $ / percentile; dev / val, forward all too few trades):
   BTC S4 $1012 63 / $991 55; S5 $816 19 / $971 42; S6 $1063 72 / $1102 55; **S7 $1483 100 (in-sample: its settings
   were chosen there) / $928 47**. Gold S4 $1120 77 / $1084 72; S5 $905 30 / **$1249 97.5 (skill candidate)**; S6 $865 24
   / $1166 63; S7 $930 48 / **$816 1.8**. Reading: nothing out of sample beats luck except gold S5 validation - after a
   below-median development and among ~16 out-of-sample comparisons (about one expected above the 95 % bar by chance),
   so a lead to watch on forward data (10 trades so far), not evidence. S7 on gold validation is worse than 98 % of
   random entries with the same stops and targets. Tests: `tests/backtest/test_universes.py` (6), API.
18. **H4: time machine (2026-10-23).** The trade export now keeps every trade's tracked events (`events`; S7 also
   `arm_time_ms`, `tf_ms`) - every other field byte-equal before / after on both markets. `arven.time_machine`:
   timeline items (S7 setup at the arming bar's close, fills, TP hits, stop moves, closes, result with the fresh
   $1000 account) and `check_no_lookahead` (0 problems on all 936 BTC trades; account = export on all 12 files).
   `config/time_machine.yaml`: BTC Covid 2020, $69k 2021, LUNA 2022, FTX 2022, ETF 2024, fresh 2026; gold Covid 2020,
   $2000 in 2020, records 2024, fresh 2026. `scripts/research/time_machine.py` refuses the sealed test period (also a
   test over the config) and leaves out trades that close more than 30 days after the window (one S6 gold trade
   held from 2020 to 2022 had stretched a scenario to 39 000 candles). Page `#/replay`: lightweight-charts player,
   ×1-×64, scrubber, next event, a short hold on each event, plain-words feed (ru / en). Tests:
   `tests/unit/test_time_machine.py` (7), API; e2e replay / universes / events 12 passed. Full suite 2513 passed (the
   module-boundary test needed `backtest/universes.py` in its list of tracker-based modules - it had been failing
   since the H3 commit `5f885ea`, run then only on the new tests).

Smoke run on partial data (scratch dir): ingest/quality/features fine; S4-S6 gave 0 signals only because the partial
data has holes (the 4h EMA filter needs 250 consecutive 4h bars) - confirmed on the full history: S4-S6 trade
normally there (docs/RESULTS_GOLD.md).

## S7 owner-label outcomes (2026-10-21, analysis only, nothing changed)

Owner asked how the setups they marked "my pattern / unsure / not mine" in the two review rounds actually traded.
One-off script `data/tmp/s7_label_outcomes.py` (git-ignored; output `data/tmp/s7_label_outcomes.json`): 171 of 191
labels re-detected with their round's detector parameters (matched by id and levels), each simulated on its own (no
one-trade-at-a-time), CFD costs, $1000 / 1 % account replay per group. All setups are development-period (2020-2023.07).

| Trade plan | yes (39 setups) | unsure (113) | no (19) |
|---|---|---|---|
| live E3/S1 | 19 tr, win 47 %, +2.40 R, $1002 | 57 tr, 58 %, +10.91 R, $1145 | 9 tr, 22 %, -3.11 R, $953 |
| baseline E1/S2 | 15 tr, 80 %, +7.07 R, $1094 | 45 tr, 44 %, +4.62 R, $1104 | 8 tr, 25 %, -1.32 R, $1010 |
| E3/S3 (close) | 19 tr, 58 %, +1.19 R, $1070 | 57 tr, 42 %, +1.32 R, $1001 | 9 tr, 56 %, -0.23 R, $1030 |

"no" is the worst group under every plan, but the samples are tiny (8-19 trades): only yes+E1/S2 has a 95 % bootstrap
interval above 0 (+0.05..+0.87 R), one cell of nine and in-sample - a lead, not evidence. The labelled setups are the
baseline detector's (no FVG, freeze 0.236), not the live configuration's.

## S7 position-sizing study (2026-10-21, analysis only, strategy unchanged)

`scripts/research/s7_risk_study.py` -> `data/s7_study/risk_study.json`: the exported S7 trades (dev 167 / val 102 /
forward 21, CFD) replayed on $1000 with fixed 0.25-5 %, a drawdown brake (half risk below -10 %, quarter below -20 %) and
half Kelly fitted on development (7.9 %), plus a seeded 100-trade bootstrap. Mean R dev +0.285, val+forward -0.084.
Continuous 2020 -> 2026-10: 0.5 % $1179 (DD 10 %), 1 % $1331 (DD 17 %), 2 % $1845 (DD 35 %), 5 % $3455 (DD 70 %),
half Kelly $4382 (DD 86 %); validation+forward alone: 0.5 % $940, 1 % $874, 2 % $798, half Kelly $270. With 0.01 BTC
lots a $1000 account cannot size below ~0.35 % on average (single trades up to 2 %). Sizing does not create an edge:
every rule loses out of sample; the larger the risk, the larger the loss. Recommendation given to the owner: no real
money; paper at 0.25-0.5 %; 0.5-1 % with the drawdown brake only after an out-of-sample edge is shown; never > 2 %.

## Phase

**Current: real-time signals work** - `arven live run` (docs/LIVE_SIGNALS.md) evaluates every enabled strategy of `config/live.yaml` at each 15m close on fresh Binance data and stores, tracks and alerts the signals; see "Live signal loop" below.

**The 10-stage thesis-core roadmap (Stages 0-10) is complete.** The owner has since approved a larger,
separate build-out described in `docs/ARVEN_MASTER_PROMPT.md` - a multi-timeframe event-driven engine, a
new strategy, Telegram alerts and a web dashboard, aimed at a usable signal product rather than only the
diploma - tracked as its own phase sequence (see "Signal-product build-out" below), kept strictly additive
so the Stages 0-10 pipeline and its golden `result_hash 3eca0a70...` keep reproducing unchanged. **Phases
1-6 of that build-out are implemented and tested**: `arven.engine` (`StrategySpec`, `BarCloseEvent`,
`EventClock`/`SimulatedEventClock`/`LiveEventClock`; per-timeframe feature tables and `MultiTFView` with
their truncation/perturbation leakage suite; the `EngineSignal`/TP-ladder/grading types);
`arven.backtest.event_engine.EventBacktester` (the event-driven backtest loop on the unchanged Stage 4
execution layer, proven `result_hash`-identical to the legacy `Backtester` for the 1h Stage 5 pipeline);
`arven.backtest.paper_tracker` (resolves a signal's TP ladder/stop forward on 1m bars, net of fees/
slippage, in R-multiples); `arven.paper.runtime` + `arven paper runtime`/`heartbeat` (the always-on polling
loop around the existing, unmodified `run_paper_tick`); `arven.telegram` + `arven telegram send`/
`commands`/`test` (alerts, bot commands, a persisted outbox - never a real order) - see "Signal-product
build-out" below for what was and was not validated. **Phase 5's own gate (a 48-hour soak on live public
data) remains deliberately not run** (owner's choice, recorded below) **and Phase 6's "owner supplies
token for a live test" step has not happened either** - no real `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_IDS`
have been provided in any session so far; everything is validated offline, against fakes. **Phase 7
(strategy S4 "Impulse-Retest") is split into 7a/7b, the same way Stage 9 was split into 9a/9b**: 7a (the
formal spec, `docs/strategy_impulse_retest.md`, and the causal swing/impulse/zone/trendline/trigger/target
detection math, hand-tested in isolation) is done. **7b is itself split into two parts** (the same
scope-management precedent as 9a/9b and 7a/7b themselves): part 1 - `arven.backtest.strategy_s4_provider`,
the `SignalProvider` adapter wiring S4's detection math into a real `EventBacktester`-compatible provider,
plus both its `Signal` (backtest) and `EngineSignal` (paper/live) renderings, verified end to end against a
hand-built scenario (including two real bugs found and fixed before any evaluation ran - see
"Signal-product build-out" below) - is done. Part 2 (the development backtest, windowed robustness,
baselines, cost stress, per-regime-like breakdown, and forward paper) is the explicit next step, not yet
started. Stage 11 (the sealed-test final evaluation) remains untouched, by design (master-prompt phase 12,
owner-gated, exactly once).
- Stage 10 (LLM explanations/Q&A + the Streamlit dashboard) is complete: implemented, unit-tested, and the
  dashboard itself was smoke-tested against this machine's real local data; the explain/Q&A LLM calls have
  not yet been made against the real Anthropic API (same acknowledged gap as Stage 9b - no API key was
  available in that session). See "Stage 10" below.
- Stage 9b (news ingestion + LLM structuring) is complete: implemented and unit-tested against fakes (not
  yet real-API-tested, not wired into any decision/risk logic - see "Stage 9b" below). News source is RSS,
  not CryptoPanic (its free API tier was discontinued in early 2026, found during design).
- Stage 9a (macro calendar + risk-engine event blackout) is complete: implemented, validated, approved and
  committed (`b67afd0`). The risk engine's 8th rule (rule 2, deferred since Stage 5) now exists: a real,
  officially-sourced FOMC/CPI/NFP calendar vetoes new entries within `macro_blackout_window_hours` (default
  1.0h) of a scheduled release, using only the *scheduled* time, never the released value. See "Stage 9a"
  below.
- Stage 8 (the paper-signal loop) is complete: implemented, validated, and produced the project's first
  genuinely forward, out-of-sample result (baseline −14.9% over 94.4 days; the logistic MetaFilter flat at
  +0.06% on 2 trades) — consistent with Stage 7's finding that Stage 6's single-run +8.6% does not
  generalize. See "Stage 8" below.
- Stage 7 (walk-forward evaluation, WFO) is complete: implemented, validated, approved and committed (see
  below). Headline finding: Stage 6's single-run +8.6% result does not replicate under genuine walk-forward
  evaluation — see "Stage 7" below.
- Stage 6 (ML meta-filter) is complete: implemented, validated, approved and committed (`e9b7c72`).
- Stage 5 (regime, strategies, decision, risk) is complete: reviewed, approved and committed (`2298e5a`).
- Stage 4 (backtester) is complete: reviewed, approved (including the final `liquidation_includes_funding =
  true` decision) and committed (`8009719`, docs correction `a6da56b`).
- Stage 3 (features) is complete: reviewed, approved and committed (`6ac57d4`).
- Stage 2 is complete: the full backfill 2020-01-01 → 2026-07-01 is ingested and verified (see below).
- Split dates, the DuckDB index/storage design and the 300 s OI availability delay are unchanged. Stage 9b
  adds two new, self-contained packages (`src/arven/news/`, `src/arven/llm/`) and two new DB tables
  (`news_items`, `news_events`, `schema_version` bumped to 2, purely additive DDL) - it changes no existing
  file's logic at all and is not called from anywhere else in the codebase yet (enforced by a static test);
  one new declared dependency, `python-dotenv` (already present in this venv, now explicit in
  `pyproject.toml`), for reading `ANTHROPIC_API_KEY` from a local `.env`. `cli.py` gained additive `news
  run`/`show` subcommands only - deliberately **not** added to the existing hourly Windows Scheduled Task,
  so no LLM API cost is incurred without an explicit, separate invocation.
- Stage 9a changes no Stage 0-8 decision/execution logic beyond adding the one new, optional, default-off rule 2:
  `src/arven/core/macro_config.py` is new and additive (a CSV loader, no I/O beyond that); `RiskEngine` and
  `Stage5Pipeline` both gained one new `macro_events: tuple[MacroEvent, ...] = ()` constructor parameter
  (empty by default — byte-identical to every previously-committed result unless a caller opts in);
  `config/risk.yaml` gained one new required field (`macro_blackout_window_hours`); `cli.py`'s shared
  `_build_pipeline` helper now loads the real calendar by default for *new* `backtest run`/`paper run`
  invocations only (`wfo_runs.py` deliberately left untouched, so Stage 7's committed results stay exactly
  reproducible).
- Stage 8 changes no Stage 0-7 decision/execution logic: `src/arven/paper/` is new and additive, driving the
  real, unmodified `Backtester`/`Stage5Pipeline` via `runs.execute_run` (the same function `arven backtest
  run` uses); the only change to existing core code is one new `BacktestPeriod.FORWARD` member in
  `core/splitguard.py` (implementing a period `docs/architecture.md`'s own "Data periods" table already
  listed from the start, not a new design decision) plus one new config field
  (`download.rest_base_url`, excluded from `config_hash()` like the rest of the `download` section).
  `cli.py` gained additive `paper run`/`show`/`status` subcommands.
- Stage 7 changes no Stage 0–6 behaviour: `src/arven/wfo.py` and `src/arven/wfo_runs.py` are new, additive
  modules that only *call* Stage 6's existing, unmodified primitives (`generate_folds`,
  `purge_and_embargo_train_mask`, `validation_mask`, `run_walk_forward`, `select_threshold`, `fit_isotonic`)
  and the real, unmodified `Stage5Pipeline`/`Backtester`; `cli.py` gained additive `wfo run`/`wfo show`
  subcommands; no config schema, dependency, or existing-file logic changed.
- Stage 1 + Stage 2 are committed on branch `feat/historical-data` (commit `efb6677`), followed by a docs commit
  (`4be9329`), the Stage 3 commit (`6ac57d4`), the Stage 4 commit (`8009719`), a docs-only correction
  (`a6da56b`), the Stage 5 commit (`2298e5a`), the Stage 6 commit (`e9b7c72`), the Stage 7 commit
  (`aa43c1b`), the Stage 8 commit (`f4f3787`) and the Stage 9a commit (`b67afd0`). Stage 9b is included in
  this commit.

## Stage 3 — features (v1)

**What was built** (see "What exists" for files): a causal feature builder that turns the stored 1m-derived bars,
funding and open interest into **61 columns per 1h bar close** (56 952 rows, 2020-01-01 00:00 → 2026-06-30 23:00 UTC),
cached as `data/features/v1/features_1h.parquet` + `manifest.json`.

**Feature groups (v1)** — every window is in `config/features.yaml`:

| Group | Columns |
|---|---|
| Returns | `h1_ret_{1,4,24,72,168}`, `h4_ret_{1,6,30}`, `m15_ret_{1,4}` |
| Volatility | `h1_atr_pct`, `h4_atr_pct`, `h1_cc_vol_{24,168}`, `h1_vol_ratio`, `h1_parkinson_24`, `m5_rv_{1h,24h}` |
| Trend | `h1_/h4_ema_dist_{20,50,200}`, `h1_/h4_ema_slope`, `h1_/h4_adx`, `h1_donchian_pos_{24,168}` |
| Momentum | `m15_/h1_/h4_rsi`, `h1_macd_hist`, `h1_bb_z`, `h1_bb_width` |
| Volume / candle | `h1_rel_volume`, `h1_rel_trades`, `h1_/h4_taker_buy_ratio`, `h1_body_ratio`, `h1_upper_wick`, `h1_lower_wick` |
| Funding | `fund_rate`, `fund_z`, `fund_sum_last_3`, `fund_hours_to_next`, `funding_available` |
| Open interest | `oi_chg_{1,4,24}h`, `oi_z`, `oi_top_ls_log`, `oi_taker_ls_log`, `oi_age_s`, `oi_available` |
| Time | `time_hour_{sin,cos}`, `time_dow_{sin,cos}` |
| Quality | `feat_ready` (1 if every *required* feature is finite; OI features are optional) |

**Point-in-time rules as implemented**
- Decision time `t` = a 1h bar close. Row `t` uses only records with `available_at <= t`; the bar closing at `t` is included
  (with `bar_availability_delay_seconds > 0` it is not). Fills belong to the backtester (next bar's open).
- 4h / 15m / 5m data are joined to the 1h grid with a backward as-of join on `available_at` (`features/asof.py`, the only join
  used). A bar older than its own timeframe is NaN, never carried forward.
- Each timeframe is computed on a gap-free grid: missing or incomplete bars are NaN rows, so `shift(k)` means k bars.
- Rolling windows are explicit shifted additions; a NaN in a window gives NaN. **Recursive indicators (EMA, Wilder RSI/ATR/ADX)
  are seeded at the first stored bar and emit only after `ceil(5 × period)` valid inputs** (`warmup_factor`, configurable). A NaN
  input resets them. Consequence: `h4_ema_dist_200` needs 1 000 4h bars, so the first `feat_ready` row is
  **2020-06-15 16:00 UTC** (52 951 ready rows).
- **Builds always start at the first stored bar.** Dropping early history changes recursive features slightly (tested and documented),
  so the cache is the canonical form; a live loop must compute over the same history (Stage 8, renumbered 2026-10-01).
- Nothing is interpolated or forward-filled. Values are NaN or finite, never ±inf.
- Missing-data policy (settles former Stage 3 input decisions):
  - **OI**: latest snapshot with `available_at <= t`, used only if its timestamp is ≤ `open_interest.max_staleness_seconds`
    (900 s) old. OI changes and the z-score use hourly as-of values, so source gaps yield NaN instead of shifting windows; the
    z-score needs ≥ 90 % of the trailing 720 h. OI features are NaN before 2020-09-01.
  - **Funding**: latest record with `available_at <= t`, NaN if older than 1.5 intervals; windows count *contiguous* settled fundings.
  - **Zero-volume bars**: 0/0 ratios are NaN (e.g. taker-buy ratio), a real 0 volume gives `rel_volume = 0`.
  - **2021-05-15 00:20 anomaly**: the 1m-derived values are used as decided in Stage 2; nothing is patched.

**Validation (2026-09-28)**
- Full suite: **403 tests pass** (109 from Stages 1–2, 294 new). New: `tests/features/` (indicators against hand-computed cases
  and naive references, as-of/alignment, warm-up declarations, funding/OI policies, config, registry, builder, cache) and
  `tests/leakage/`.
- Leakage suite (`tests/leakage/`): for **every** registered feature, a **truncation test** (row at `t` from all data equals the
  row from only data available at `t`) and a **perturbation test** (replacing everything that became available after `t` with
  garbage changes nothing), both bitwise-exact; also with a bar availability delay and late-published funding. **Canary tests**
  prove the checks catch a future-close feature, a centred rolling mean and a full-sample z-score, and do not flag a causal control.
  **Static rules** (AST scan): no `shift(-k)`, centred windows, `bfill`/`ffill`/interpolation, whole-series mean/std/rank/quantile,
  and `features/` imports nothing from `data`, storage, `ml`, `strategies`, `risk`, `backtest`, `regime`, etc.
- Real-data spot check (`ARVEN_REAL_DATA_TESTS=1 ARVEN_REAL_DATA_SAMPLES=200`, development period only, read-only; inputs end at
  2023-07-01): **passed**. Truncation test at 235 decision times (200 random from 2020-07 on, 25 early, 7 hand-picked: OI start
  2020-09-01, the 2021-06-22 OI gap, the 2021-05-15 anomaly, 2021-12 and 2022-03) and perturbation test at 13 of them: no feature
  changed, all 61 columns compared bitwise. Also: `h1_ret_1`/`h4_ret_1` equal an independent SQL computation at 25 random times,
  and value invariants hold on all 30 648 development rows. Runs in about 1 minute.
- Real build: 6.7 s, **peak working set 282 MB** (target < 500 MB). Two consecutive builds gave the identical content hash
  (`c06b09e7…`); the manifest records definition hash, feature-config hash, app-config hash, source-data fingerprint, git commit.
- `arven features check`: definition hash, column list, content hash and value invariants (RSI/ADX in [0,100], ratios in
  [0,1], no ±inf) all pass. Statistics are printed for the **development period only**; the sealed test period was not inspected.

**Data findings surfaced by the feature build (not pipeline bugs)**
- Binance metrics files have **empty `sum_toptrader_long_short_ratio` for almost every row from 2021-12 to 2022-12** (only parts of
  2022-06 and 2022-12 are filled) and **empty `sum_taker_long_short_vol_ratio` from 2021-12 to 2022-05**. The stored NULLs match
  the raw files (Stage 2 verified stored vs raw). So in the development period `oi_top_ls_log` is NaN for 44 % of rows and
  `oi_taker_ls_log` for 29 %; `oi_chg_*` / `oi_z` are NaN for 19–22 % (mostly the pre-2020-09 boundary).
- `oi_age_s` has mean 300.1 s (the publication delay) and maximum 900 s (the staleness limit) in the development period.

## Stage 4 — backtester

**What was built** (see "What exists" for files): a deterministic, event-driven 1m execution backtester. It turns a
`SignalProvider`'s `Signal`s (decided at each 1h bar close, from Stage 3's `feat_ready` grid) into fills, funding
settlements, exits and a full order/fill/trade/equity ledger, with fees, slippage, isolated margin and liquidation.

**Execution model**
- **Clock:** `SimulationClock` iterates the pre-computed 1h decision grid of the requested window; nothing in
  `backtest/` reads the wall clock (`test_backtest_static_rules.py` enforces this with an AST scan).
- **Decision → order → fill:** at `t`, the provider sees a `FeatureView` (raises `LookAheadError` for any row after
  `t`) and a `PortfolioSnapshot`, and returns a `Signal | None`. LONG/SHORT becomes an order that fills at the open
  of the 1m bar at `t + latency_minutes` (default: `t` itself, i.e. the next bar). If that bar is missing, the order
  is `CANCELLED(no_market_data)` — no forward search.
- **Costs:** taker fee (`costs.yaml`), and slippage = `s * (fixed_bps + volatility_multiplier * bar_range_bps) / 1e4`
  on the fill/exit bar's own range (`s` = `stress_multiplier` with `--stress`), adverse to the trade direction.
- **Sizing / leverage / margin:** `notional_fraction * equity`, rounded down to `qty_step_btc`; rejected (with a
  reason, never resized) if it exceeds `leverage`, falls below `min_notional_usdt`, or the isolated margin
  (`notional / leverage`) plus the entry fee exceeds the wallet.
- **Stop/target/time-stop:** distances are fractions of the fill price. In one bar, an adverse level (stop or
  liquidation) always beats the take-profit; between two adverse levels the one nearer the entry triggers first. A
  stop the market gaps through fills at the bar's open, never at the stop level. A target never fills better than
  its level.
- **Funding:** settled from the recorded rate at each funding timestamp while a position is open (entry instant
  excluded, exit instant included), at `qty * open-price-at-that-minute * rate`; a missing rate aborts the run by
  default (`costs.funding.missing_policy`).
- **Liquidation:** `liquidation_includes_funding` (new; see open issue #13) — **true** (current default): funding is
  debited from the position's isolated margin, so the liquidation price moves with the margin balance and equity can
  never go negative; **false**: the plan's original model (liquidation price fixed at entry, funding never triggers
  it — which a real long-held position with persistent positive funding can push into negative wallet equity, see
  #13). Either way, on liquidation the wallet loses exactly the (possibly funding-adjusted) isolated margin; no exit
  fee or extra slippage.
- **One position, no pyramiding:** a second entry signal while a position is open is `REJECTED(position_open)`; only
  an explicit `NO_TRADE(close_position=True)` closes early. Data gaps while a position is open close it at the first
  bar after the gap (`DATA_GAP`). An open position at the window end is force-closed at the last bar's close
  (`END_OF_PERIOD`).

**Point-in-time and split enforcement**
- `FeatureView` and `MarketData` are read-only, window-scoped, and every timestamp loaded is asserted inside the
  requested `AllowedWindow`.
- `SplitGuard.resolve(period, start?, end?)` is the only way to obtain an `AllowedWindow` (its constructor refuses to
  be called directly — `test_allowed_window_cannot_be_forged`). A range crossing a period boundary is refused. The
  sealed `test` period additionally needs `allow_sealed=True` and a non-empty `reason`; the access is appended to
  `data/backtests/sealed_test_log.jsonl` **before** any data is read, so even an aborted attempt is logged.
- Verified on real data: a development-period `arven backtest run` was refused for `--period test` without
  `--allow-sealed`/`--reason`, and no sealed-log entry was written for the refusal.

**Determinism and reproducibility**
- Money is float64 with a fixed operation order; the only randomness is `RandomEntry`'s, seeded from
  `SeedSequence(project.random_seed).spawn(n_seeds)[i]` (documented, and verified to match the plain
  `spawn_key=(i,)` construction).
- `result_hash` is a SHA-256 over the canonical (fixed column order, 10-decimals-rounded) CSV of every ledger; two
  independent runs of the same inputs give an identical hash (verified on real development-period data, and with
  golden hashes on three fixed synthetic scenarios in `test_report_determinism.py`).
- Each run's `run.json` records: `git_commit` + `git_dirty`, the feature cache's `definition_hash` /
  `data_sha256` (content hash) / `source_fingerprint`, a fingerprint of the 1m+funding arrays actually used,
  `app_config_hash`, `backtest_config_hash`, the period/window, `touched_test_set`, the provider's parameters and a
  `provider_hash`, the random-seed derivation, per-table hashes and `result_hash`. `arven backtest verify <run_id>`
  recomputes every hash from the written files and checks that no logged data range left the window.

**Correctness validation**
- **Independent oracle:** a deliberately separate, naive bar-by-bar reference implementation of the same
  specification (no shared code with the engine) matched the fast engine exactly (trades, exit reasons, funding,
  every decision-time equity value, final wallet) on 300 seeded random scenarios covering every exit reason.
- **~30 hand-computed accounting cases**, each with by-hand expected numbers: fees, slippage (with/without stress),
  take-profit/stop/gap-through/same-bar-tie/liquidation-vs-stop-vs-target ordering, funding sign and boundary timing,
  a missing funding rate (error and assumed-rate policies), each rejection reason, latency, end-of-period close,
  a frictionless buy-and-hold matching independent price arithmetic, and both liquidation models.
- **Accounting invariants** on 150 further random scenarios: `final_wallet = initial + Σ net_pnl`; per-trade
  `net = gross_ref - slippage - fees + funding (+ liquidation loss)`; fill price = fill bar's open (adjusted); one
  position at a time; notional ≤ leverage × equity; equity never negative when `liquidation_includes_funding=true`.
- **Leakage** (`tests/leakage/test_backtest_leakage.py`): `FeatureView` refuses future rows; **prefix invariance**
  (cutting all data at `T` leaves every trade closed before `T` and the equity curve up to `T` byte-identical) and
  **perturbation** (garbage after `T` changes nothing decided or completed at or before `T`), both on 25 seeded
  scenarios; a fills-at-next-open test (a price gap exactly at the decision time proves the fill is not the signal
  bar's close); a test-only provider with raw access to the market's future is caught by its impossible return
  (> 0.3 on a 30-day driftless random walk after costs), while 24 seeded `RandomEntry` runs on the same data show no
  edge before costs (mean gross PnL within 4 standard errors of 0) and a loss after costs matching the fee+slippage
  total almost exactly.
- **Static rules:** an AST scan forbids wall-clock/file/unseeded-random calls and enforces that `backtest/` imports
  nothing from `data`, `features`, `strategies`, `risk`, `regime`, `ml`, `decision` or `duckdb`, and that no
  lower-layer or later-stage package imports `backtest`/`runs`.

**Baselines on the real development period** (2020-01-01 → 2023-07-01, 1 277 days, repo `config/backtest.yaml` +
`costs.yaml`, `liquidation_includes_funding=true`, git `6ac57d47` + Stage 4 working tree, `touched_test_set=false`;
`arven backtest baselines --period development`, artifacts in `data/backtests/baselines-20260928T184751Z-b5abd36a/`):

| metric | no_trade | buy_and_hold | random p5 | random mean | random p95 |
|---|---:|---:|---:|---:|---:|
| total_return | 0 | −1.905 | −0.562 | −0.083 | 0.612 |
| net_pnl (USDT) | 0 | −19 046 | −5 616 | −829 | 6 115 |
| max_drawdown | 0 | 1.155 | 0.194 | 0.388 | 0.616 |
| n_trades | 0 | 1 | 100 | 100 | 100 |
| win_rate | n/a | 0 | 0.400 | 0.478 | 0.551 |
| profit_factor | n/a | n/a | 0.488 | 0.918 | 1.480 |
| fees (USDT) | 0 | 5.0 | 644 | 953 | 1 372 |
| slippage (USDT) | 0 | 4.2 | 325 | 476 | 693 |
| funding (USDT, signed) | 0 | −19 041 | −136 | −3.0 | 118 |
| turnover | 0 | 2.44 | 187 | 198 | 207 |
| exposure_time | 0 | 0.570 | 0.078 | 0.078 | 0.078 |
| sharpe | n/a | −0.205 | −1.099 | −0.149 | 0.808 |

- **no_trade:** equity exactly flat at 10 000 (asserted).
- **buy_and_hold** (`notional_fraction=1.0`, i.e. up to the 3× leverage cap): entered 2020-06-15 (the first
  `feat_ready` decision) at 9 293.92, and was **liquidated 2022-06-13** at a reference price of 24 004.01 — a net
  loss of 19 045.45 USDT (−190.5 % of the initial equity), *before* the price ever fell far enough alone: cumulative
  funding of −19 040.46 USDT over ~2 years eroded the isolated margin, and with
  `liquidation_includes_funding=true` that pulled the liquidation trigger price up to meet BTC's June 2022 decline.
  This is the same scenario that originally exposed the fixed-liquidation-price model's flaw (see open issue #13),
  now confirmed on real data: re-run with `liquidation_includes_funding=false` (the plan's original D11 model), the
  identical trade instead runs to `END_OF_PERIOD` and ends at 12 262.68 (+22.6 %) — but along the way, at
  2022-11-21 22:00 UTC, **equity reaches −2 585.50 USDT**, which no real isolated-margin account allows. Same market
  data, same entry, only this one switch differs (`result_hash` for `false`: `b55d9d0c…`).
- **random_entry** (200 seeds, 100 trades of 1 440 min = 24 h each, `notional_fraction=1.0`, 50/50 long/short): mean
  net PnL is negative (−829 USDT) and mostly a function of costs — mean fees + slippage + |funding| ≈ 953 + 476 + 3 ≈
  1 432 USDT, against a mean net loss of 829 USDT, so roughly two-thirds of the average loss is explained by
  round-trip costs on a direction with no edge, consistent with a fair coin flip. All 200 seed schedules and their
  `result_hash`es are stored in `random_entry/seeds.csv`; the seed-0 self-check reproduced exactly.
- These are baseline measurements of the simulator (its costs, its leverage/liquidation mechanics), **not evidence
  that any strategy is profitable** — no strategy exists yet.

**Known limitations, all deliberate MVP simplifications (documented, not bugs)**
- No maker fills (`require_taker_only` raises `ConfigurationError` if `costs.yaml` ever selects maker); no tiered
  maintenance-margin schedule; no order-book/market-impact model; single funding-interval assumption
  (`costs.funding.default_interval_hours`, informational elsewhere) drives the funding grid actually queried.
- `qty_step_btc`, `min_notional_usdt` and `maintenance_margin_rate` are stated assumptions, not verified against
  Binance's current live schedule (open issue #12).
- The 3 real strategies, the ML meta-filter and the risk engine are Stage 5/6 — the backtester takes a
  `SignalProvider`, not a strategy; only the 3 baselines exist in Stage 4, as the roadmap requires.

**Operational notes**
- `con.executemany` / a single large parameterised `INSERT` into a table with a `PRIMARY KEY` ART index is
  pathologically slow in the installed DuckDB version (≈20 ms/row; 5 000 rows ≈ 94 s — this is what caused the first
  integration-test run to hang for several minutes). Stage 2's own ingestion never hits this, since it loads via
  `COPY … FROM` a file. Test helpers now use the same idiom (`bt_helpers.bulk_insert_1m/_funding`, `COPY FROM` a temp
  CSV): 5 000 rows in ≈0.09 s. Nothing in `src/` was affected; this is a test-infrastructure fix only.
  **Update (Stage 8, 2026-10-03): this time it did affect `src/`** — `rest_ingestion.py`'s first implementation hit
  the exact same pitfall (measured ~33 s per 1000-row REST page) and was fixed with the identical staged-bulk-load
  idiom; see the "Stage 8" section above for the real run this was found on.

## Stage 5 — regime, strategies, decision, risk

**What was built:** a rule-based regime detector, three independent strategies, a decision engine (regime
gate + weighted vote) and a risk engine (8 ordered veto/reduce rules), wired into one
`Stage5Pipeline` that implements Stage 4's `SignalProvider` protocol unmodified — `arven backtest run
--provider pipeline` runs it exactly like the Stage 4 baselines.

**Regime detection** (`config/regime.yaml`, `src/arven/regime/detector.py`)
- **Trend** (`TREND_UP` / `TREND_DOWN` / `NO_TREND`): `h4_adx >= 20` **and** `h1_adx >= 15` (the 1h
  confirmation), then direction from the sign of `h4_ema_slope` agreeing with the sign of `h4_ema_dist_200`
  (price vs EMA200); any disagreement (including ADX high but slope/price disagreeing) is `NO_TREND`.
- **Volatility** (`LOW` / `NORMAL` / `HIGH`): percentile rank of `h1_atr_pct` in its own trailing window
  (causal — only bars up to and including `t`; NaNs filtered, not treated as zero), default window ~1 year
  (architecture's own wording), classified once at least 720 (30 days) valid values exist, `NORMAL` before that.
- **Stress** (flag, not an axis): `|fund_z| >= 3.0` or `|oi_chg_1h| >= 0.05` (log change).
- **Hysteresis:** a candidate trend state must be the raw classifier's output for `min_dwell_bars = 3`
  consecutive decisions (including the very first transition away from `NO_TREND`) before the detector
  actually switches; a reverting candidate resets its counter. Stateful, causal, reset at the start of every run.

**The three strategies** (`config/strategies.yaml`, `src/arven/strategies/`) — each reads only Stage 3
features, returns a `CandidateSignal(direction, strength, stop_pct, take_profit_pct, ...)` or `None`, and
never sees the other strategies, the portfolio, or the regime label (regime *gating* is config declared per
strategy and applied by the decision engine, not by the strategy):
1. **Trend/Momentum** (architecture #1): direction from the 1h EMA(20) vs EMA(50) relationship (derived from
   `h1_ema_dist_20 - h1_ema_dist_50`); a 4h filter requires `h4_adx >= 20` and the 4h EMA-slope sign to agree;
   optional MACD-histogram confirmation (on by default); blocked if `h1_rsi` is already extreme in that
   direction (75 / 25). Strength = `h4_adx / 50`, clamped. Stop = `1.5 × h1_atr_pct`, target = `3 × h1_atr_pct`.
   Gated to `TREND_UP`/`TREND_DOWN`, any volatility, not during stress.
2. **Breakout** (architecture #3, volatility breakout): a squeeze is detected causally — `h1_bb_width` must
   have been strictly below the 25th percentile of its own 480-bar (20-day) trailing window (percentile and
   squeeze check both computed **excluding the current bar**, so a bar can't set its own threshold) at some
   point in the last 48 bars (2 days); the trigger is `h1_donchian_pos_24` at or beyond 0.95 / 0.05 **now**.
   Stop = `2 × h1_atr_pct`, target = `3 × h1_atr_pct`. Gated to `NORMAL`/`HIGH` volatility, any trend.
3. **Mean Reversion** (architecture #2): contrarian on `h1_bb_z` beyond ±2.0, confirmed by `h1_rsi` beyond
   35/65 in the same direction. Stop = `1.0 × h1_atr_pct`, target = `1.5 × h1_atr_pct`. Gated to `NO_TREND`
   only ("RANGE" in the architecture's wording), not during stress.
- The 4th architecture strategy (funding/positioning contrarian) is out of the explicit Stage 5 scope and was
  not built.

**Decision engine** (`src/arven/decision/engine.py`) — architecture section 13, steps 1-3, 5, 6 (step 4, the
ML filter, is Stage 6 and was **omitted**, not stubbed):
1. **Regime gate:** each strategy's `allowed_trends`/`allowed_vols`/`require_not_stress` (config) filters its
   candidate out entirely if the current regime doesn't match; gated-out ids are kept for logging.
2. **Weighted vote:** `score = Σ weight_s × strength_s` over the *allowed* candidates, separately summed for
   each direction (`pos_mass`, `neg_mass`); `score = pos_mass - neg_mass`. Equal weights (1.0 each) by default.
3. **Conflict rule:** `pos_mass >= 0.35` **and** `neg_mass >= 0.35` (both, not just close) ⇒ `NO_TRADE`.
4. **Threshold:** `|score| < 0.35` ⇒ `NO_TRADE`. No candidates ⇒ `NO_TRADE`. These are also the *only* ways to
   reach `NO_TRADE` here — the default outcome is always `NO_TRADE` unless something actively clears both bars.
5. **Output:** the winning direction's contributing strategies, a weighted average of their stop/take-profit
   hints, the most conservative (shortest) of their holding caps, and `confidence = |score| / Σ(all weights)`.
- The decision engine never receives the portfolio (enforced by a static test on its signature): sizing and
  vetoing is entirely the risk engine's job.

**Risk engine** (`config/risk.yaml`, `src/arven/risk/engine.py`) — architecture section 14, an ordered
pipeline of independent rules, each vetoing or reducing, never creating/flipping a direction. Rule 2 (macro
event blackout) was deferred at Stage 5 time ("later stage" = Stage 9) and is now implemented — see "Stage
9a" below for the full design; all 8 rules now exist:
1. **Data-quality gate:** `feat_ready != 1` ⇒ veto `stale_or_incomplete_data`.
2. **Macro-event blackout** (Stage 9a): veto `macro_event_blackout` within `macro_blackout_window_hours`
   (default 1.0h) of any scheduled FOMC/CPI/NFP release in `config/macro_events.csv` — see "Stage 9a" below.
3. **Volatility guard:** `regime.stress` ⇒ veto `extreme_volatility_stress` (config `veto_on_stress: true`);
   `HIGH` volatility ⇒ size ×0.5.
4. **Funding guard:** entering the side that *pays* extreme funding (`direction × fund_z`) — ×0.5 at
   `|·| >= 2.0`, veto `extreme_funding` at `|·| >= 4.0`. Longs pay on a positive rate, shorts on a negative
   one (matches `arven.backtest.accounting`'s sign convention exactly — the same fact, not re-derived).
5. **Stop & target bounds:** the decision layer's hint is clamped to `[0.3%, 8%]`; the target is *extended*
   (never shortened) to meet `take_profit_pct >= stop_pct × 1.2` if it doesn't already.
6. **Position sizing:** `notional_fraction = risk_fraction_per_trade (0.75%) / stop_pct`, then the guard
   multipliers above, capped at `max_notional_fraction = 1.0` and at `config/backtest.yaml`'s `leverage` (one
   source of truth — risk.yaml does **not** duplicate leverage or `maintenance_margin_rate`).
7. **Portfolio limits** (checked early, before 3-6, since nothing downstream matters if any holds): a position
   or a pending order already exists ⇒ veto `position_already_open`; max daily loss 2% (UTC-day baseline,
   resets each day) ⇒ veto `max_daily_loss_halt`; running-peak drawdown ≥ 20% ⇒ veto `max_drawdown_halt` until
   it recovers to ≤ 15%; 3 consecutive losing trades ⇒ veto `loss_streak_cooldown` for 24 decision bars. All
   four are stateful and causal (driven only by the sequence of `PortfolioSnapshot`s the engine itself
   observes at each decision — never a peek at a future trade's outcome), reset at the start of every run.
8. **Liquidation-distance check:** the relative liquidation distance is a pure function of
   `(side, leverage, maintenance_margin_rate)` alone — **not of price** — reusing
   `arven.backtest.margin.liquidation_price` (one pure function; nothing here touches the engine, execution or
   accounting). Veto `stop_too_close_to_liquidation` if that distance is less than `1.5 ×` the (bounded) stop.
- A veto or a pass-through (`NO_TRADE` proposed) always returns `None` (no `Signal`) to the backtester; every
  outcome — pass, reduce, veto, or pass-through — is recorded with its reason and numbers in the pipeline's
  `DecisionRecord` history.

**Module separation, enforced mechanically** (`tests/pipeline/test_stage5_static_rules.py`,
`tests/backtest/test_backtest_static_rules.py`): `regime` imports nothing from `strategies`/`decision`/`risk`;
`strategies` imports nothing from `risk`/`decision`/`regime`/`arven.backtest.margin`; `risk` imports nothing
from `strategies`, and only `arven.backtest.provider` (types) + `arven.backtest.margin` (one pure function)
from `backtest`; `decision` imports nothing from `backtest` at all; nothing in any of the four imports
`arven.backtest.engine`/`execution`/`accounting` (would bypass the engine); no lower layer or Stage 6+ package
imports any Stage 5 package. The per-regime analysis report (`arven.reports`, see below) deliberately lives
**outside** `arven.decision` — it runs only after a backtest finishes and never feeds back into a live
decision, so it is not bound by the same separation rules, and a static test confirms the dependency stays
one-directional (`regime`/`strategies`/`decision`/`risk` never import `arven.reports`).

**Validation**
- **Unit tests** (`tests/regime/`, `tests/strategies/`, `tests/decision/`, `tests/risk/`): hand-computed cases
  for every rule branch of the regime classifier (including hysteresis/dwell and its reset), each strategy
  (using a hand-built `FeatureView` via the real Stage 3 column names, so a renamed column fails the test
  rather than silently reading NaN), the decision engine's gating/vote/conflict/threshold/confidence
  arithmetic, and all 8 risk rules including the 4 stateful circuit breakers. One real bug was found and fixed
  by these tests: the breakout strategy's compression check used `>` instead of a strict `<`, so a perfectly
  flat (untouched) `bb_width` series tied its own percentile and was wrongly read as "compressed" — fixed to
  `>=` (i.e. strictly below the threshold only).
- **Leakage / causality** (`tests/pipeline/test_leakage.py`): prefix invariance (cutting all data — both the
  Stage 3 feature table and the raw 1m market — at time `T` leaves every trade closed before `T` and every
  decision-time equity value up to `T` byte-identical) and perturbation (replacing everything after `T` with
  Stage-3-plausible garbage changes nothing decided or completed at or before `T`), each on 5 seeded 250-day
  scenarios; a further check that the regime detector's own hysteresis-state sequence up to `T` is identical
  under perturbation (proving the sequential state itself doesn't leak, not just the final trades). `FeatureView`'s
  existing `LookAheadError` guard (Stage 4) is exercised throughout, since every strategy/regime read goes
  through it.
- **Determinism / reproducibility** (`tests/pipeline/test_determinism.py`): two independent runs of the same
  inputs give an identical `result_hash`; reusing one `Stage5Pipeline` object for two `Backtester.run()` calls
  (as the engine does internally) gives the same result as two fresh objects — `prepare()` fully resets regime
  and risk state; the full decision history (not just the ledgers) reproduces exactly; `--stress` changes the
  result deterministically.
- **Accounting/execution integration** (`tests/pipeline/test_backtest_integration.py`): Stage 4's own
  invariants (`final_wallet = initial + Σ net_pnl`, one position at a time, notional ≤ leverage × equity, fill
  price = the fill bar's open, ...) hold on 30 seeded runs driven entirely by the Stage 5 pipeline on a
  volatile synthetic 1m market (needed for stops/targets/rare liquidations to actually trigger — the Stage 4
  test helper's default market is flat); every trade's tag carries its contributing strategies and regime;
  stop-exit R-multiples cluster near −1 and take-profit R-multiples clear roughly the configured minimum
  reward:risk ratio; liquidations stay under a sanity ceiling.
- **Real development-period data** (opt-in, `ARVEN_REAL_DATA_TESTS=1`, `tests/pipeline/test_pipeline_real_data.py`):
  the pipeline runs on the real database + Stage 3 v1 feature cache, reproduces its `result_hash` on an
  independent re-run, the sealed test period is refused without `--allow-sealed --reason`, the validation
  period is allowed and correctly marked `touched_test_set=false`, and the development run's own data-range
  log never reaches or exceeds its window's end.
- **Full suite:** 1338 passed, 8 skipped (3 Stage 3/4 + 4 Stage 5 opt-in real-data checks, 1 Stage-6-doesn't-exist-yet),
  ≈5 minutes. All 8 skipped tests pass when run with `ARVEN_REAL_DATA_TESTS=1` (verified together, 7 tests, ≈44 s
  — the 8th, the `ml` static-rule check, has no meaning until Stage 6 exists).

**Real backtest result** (development period, `arven backtest run --provider pipeline --period development`,
git `8009719`+working tree, `touched_test_set=false`, result_hash `3eca0a70…`, reproduced identically on an
independent re-run and via `arven backtest verify`):

| metric | value |
|---|---|
| trades | 111 (74 STOP, 37 TAKE_PROFIT, 0 liquidations) |
| total_return | −20.3% (final equity 7 973.83 from 10 000) |
| win_rate | 33.3% |
| profit_factor | 0.566 |
| max_drawdown | 20.6% (intrabar 22.3%) |
| sharpe | −1.43 |
| fees / slippage / funding | 829.19 / 640.69 / −7.04 USDT |
| exposure_time | 3.0% |

No parameters were tuned to make this positive (CLAUDE.md rule: "do not optimize parameters"), and this is a
measurement of the *framework* with unoptimized, architecture-derived defaults — not a claim that these three
strategies have an edge. The per-regime breakdown (`arven.reports.per_regime_breakdown`, printed by the CLI)
shows losses concentrated in `NO_TREND/LOW` (51 of 111 trades, −812 USDT) and `NO_TREND/NORMAL` (14 trades,
−635 USDT) — i.e. mean-reversion trades in quiet/normal-vol ranging conditions were the main drag — while
`TREND_DOWN/HIGH` was the only regime with a net positive contribution (+44.76 USDT, 7 trades). This is exactly
the kind of regime-conditional signal the roadmap's "per-regime analysis" deliverable exists to surface; it is
not evidence either way about whether the framework has value, only about where *this* unoptimized
configuration's losses concentrated.

**Known limitations, all deliberate MVP scope (not bugs)**
- No ML filter (Stage 6) and no macro-event blackout (Stage 9) — architecture explicitly places both later.
- No parameter search of any kind was performed or is provided (CLAUDE.md rule; the config values are the
  architecture's own stated defaults, e.g. "risk 0.5-1%" → 0.75%, "max leverage e.g. 3×" → uses `backtest.yaml`'s 3×).
- The regime volatility window (`window_hours: 8760`, "trailing 1-year") means the first ~1 year of the
  development period classifies mostly on partial history (`NORMAL` until 720 bars/30 days exist, then a
  percentile over a still-growing window) — matches the architecture's own stated window, not a shortcut.
- `arven.reports.per_regime_breakdown` attributes a trade to the regime at its **signal** time (when the
  decision was made), not its fill or exit time — the natural choice, since regime gating happens at the
  decision, but worth stating explicitly for anyone extending the analysis.

## Stage 6 — ML meta-filter

**What was built:** a `MetaFilter` that estimates `P(success)` for the single `ProposedDecision`
`DecisionEngine.decide()` already produced, and either passes it through unchanged or replaces its action
with `NO_TRADE`. It sits strictly between `DecisionEngine.decide()` and `RiskEngine.apply()` inside
`Stage5Pipeline`, wired through one new, optional constructor parameter (`ml_filter: MLFilterProtocol | None
= None`, default `None`) — with no filter, `Stage5Pipeline` is byte-identical to the committed Stage 5
behaviour (`tests/pipeline/test_stage5_no_ml_regression.py`, 9 tests). The ML layer can never flip direction,
create a trade, resize a position, change risk parameters, or bypass the risk engine or Stage 4 execution —
it has exactly two outcomes: pass or veto.

**Labels** (`src/arven/ml/labels.py`) — triple-barrier, resolved on 1m bars, net of the same cost functions
Stage 4 uses (`arven.backtest.costs.adverse_price`/`slippage_fraction`/`taker_fee_rate`; pure functions, not
the execution engine): stop/take-profit distances from the candidate's own hints, vertical barrier =
`max_holding_minutes`. Same-bar tie ⇒ stop wins (worst-case, matching CLAUDE.md rule 4). Label = 1 if net
return ≥ `min_net_return_for_positive_label` (0.0 — net-of-costs already implies "TP must exceed round-trip
cost"). `None` (unresolvable) if the fill bar is missing or the horizon runs past stored data. Documented
simplifications: no gap-through adjustment (uses the barrier level, not a gapped price — slightly optimistic
vs Stage 4's real fill model), no funding cost, no liquidation modelling in the label itself.

**Dataset construction** (`src/arven/ml/dataset.py`) — replays the *real* `RegimeDetector`, the real
`build_strategies`, the real `DecisionEngine`, and the real `RiskEngine` (imported directly, not
reimplemented — enforced by a static test) over development+validation, exactly as Stage 5 does, except every
candidate is risk-checked against a fixed, always-flat `PortfolioSnapshot` before being reset (D3): dataset
eligibility reflects each candidate's own merit — data-quality/stress/funding/stop-distance rules still
apply, only the *portfolio-state* rules (position-open, daily-loss halt, drawdown halt, cooldown) are
neutralised. This is deliberately not the same population a real backtest sees (which only opens one
position at a time), and is documented as such everywhere it matters. Feature row = 60 causal Stage 3
columns + 18 Stage 5 context columns (3 trend one-hot + 3 vol one-hot + stress flag + 3 contributing-strategy
flags + 3 contributing-strategy strengths + score + confidence + stop/take-profit/max-holding hints) = 78
columns total.

**Splits** (`src/arven/ml/splits.py`) — purged, embargoed, **expanding**-window walk-forward, date-agnostic
(takes plain start/end ms; a static test locks that it never imports `SplitGuard` or the app config — the
real development/validation boundary is resolved once, by the caller, through the existing `SplitGuard`, not
duplicated here). A training row is purged if its label horizon overlaps the validation block or falls within
`embargo_hours` (96) before it starts. `min_train_months=12`, `retrain_interval_months=3` (D4) — on
development+validation this produced **17 chronological folds**.

**Models** (`src/arven/ml/model.py`) — pure-numpy Newton's-method logistic regression (intercept never
regularized, deterministic) and a LightGBM adapter (`deterministic=True, force_row_wise=True,
num_threads=1`, all four seed parameters fixed from the project seed, early stopping). D7: LightGBM uses all
78 columns; logistic regression restricts the Stage-3-sourced portion to the 51 `required=True` Stage 3
columns (context columns are always finite, so aren't restricted) = 69 columns. Hyperparameters: a fixed grid
of ≤4 configurations per family (`config/ml.yaml`, D5), selected per walk-forward fold by mean validation
log-loss — no open-ended search, no sealed-test involvement anywhere. Calibration is isotonic only (D6,
stack-based PAVA), fitted on each fold's held-out validation rows, never the rows a model trained on.

**Model artifacts** (`src/arven/ml/artifact.py`) — every saved model carries the full provenance list agreed
in planning: model id/family, `git_commit`+`git_dirty`, feature/ML/app/backtest/regime/strategies/risk config
hashes, feature definition and content hashes, training/validation period bounds, random seed, the selected
hyperparameters, the complete per-fold walk-forward summary, a dataset fingerprint, the model artifact's own
SHA-256 hash, threshold, feature names, all candidate/ineligible/train/calibration row counts, raw and
calibrated metrics, warnings, environment, and `touched_test_set` (always `False` for a Stage 6 training
run — `arven.ml_runs` never resolves `BacktestPeriod.TEST`, checked both by test and by a static string
scan). `arven ml verify <model_id>` recomputes the artifact hash from the saved files.
- **One real bug found and fixed during implementation:** `LightGBMModel` originally stored the raw
  `lgb.Booster` object; pickling a freshly-trained Booster gave different bytes than pickling the same model
  after a save→load round trip (LightGBM reconstructs its pickled state from an internal text dump, and that
  round trip isn't byte-stable), so `arven ml verify` failed only for LightGBM models. Fixed by storing the
  canonical `model_str` text dump instead, with a `booster` property that reconstructs on demand; locked by
  `test_two_independently_trained_lightgbm_artifacts_with_the_same_seed_have_the_same_hash`.

**MetaFilter** (`src/arven/ml/filter.py`) — `build_row()` encodes the same 78-column row live, from the
`ProposedDecision` and the current `FeatureView` (never a later time — `FeatureView`'s existing Stage 4
`LookAheadError` guard is inherited unchanged, no new leakage-prevention code was written). `apply()` returns
the proposed decision unchanged if it's already `NO_TRADE` or `P(success) ≥ threshold` (0.55, D-approved
config default); otherwise returns it with the action replaced by `NO_TRADE` and the stop/target/holding
fields cleared. `RandomFilter` (control) — a seeded uniform rejection at a fixed rate, same interface, used
for the matched-rate control below.

**CLI** (`src/arven/cli.py`, additive only): `arven ml train --model-family {logistic,lightgbm}
[--shuffle-labels-seed N]`, `arven ml verify <model_id>`, `arven ml show <model_id>`; `arven backtest run
--provider pipeline` gained `--ml-model <model_id>` (loads a trained `MetaFilter`) and
`--random-filter-rate <p>` (the `RandomFilter` control).

**Module separation, enforced mechanically** (`tests/ml/test_ml_static_rules.py`,
`tests/leakage/test_ml_leakage.py`): `arven.ml` never imports the Stage 4 execution/accounting engine or
`duckdb` directly; the `lightgbm` package itself is imported only by `model.py` and `artifact.py` (the
version string); `regime`/`strategies`/`risk`/`decision` never import `lightgbm` or `arven.ml` (one-directional
dependency, ML depends on Stage 5, never the reverse); `features/` never imports `arven.ml.labels`
(forward-looking labels never reachable from causal feature code); `dataset.py` imports the real
`RiskEngine`, not a local reimplementation; `splits.py` takes only plain ms/int parameters, no
`SplitGuard`/app-config imports.

**Validation**
- **Leakage canaries** (`tests/leakage/test_ml_leakage.py`, 11 tests): all 5 planned deliberate-break types
  — (1) a future label folded into a feature column (structural: only `.label`/`.net_return` are ever read
  from a `LabelResult` into `x`), (2) a future feature read (`FeatureView`'s `LookAheadError`, exercised
  directly against `build_row`), (3) random temporal shuffling (a synthetic regime-flip dataset demonstrates
  shuffled train/test assignment looks *falsely* better than real walk-forward, and fold boundaries are
  proven monotonic/non-overlapping), (4) full-period normalisation (train-only standardisation is proven to
  differ from full-period statistics; calibration fit on a model's own training rows is proven to differ
  from a proper held-out fit), (5) sealed-test contamination (`arven.ml_runs` never resolves
  `BacktestPeriod.TEST`; a direct `.resolve(TEST)` raises `SealedAccessError`; fold generation is bounded
  exactly at `validation.end_ms`, never beyond).
- **Hand-computed label cases** (`tests/ml/test_labels.py`, 12 tests): known entry/stop/target/time-barrier
  combinations against by-hand expected outcomes and net returns, including a zero-cost control case and the
  same-bar-tie-favours-stop rule.
- **Purge/embargo property tests** (`tests/ml/test_splits.py`, 28 tests): exhaustive 20-seed property test
  that no purged training row's label horizon ever overlaps a validation block or falls inside the embargo.
- **Determinism**: two independent real-data training runs give identical `model_artifact_hash` and
  `training_dataset_fingerprint` for both model families (`tests/ml/test_ml_real_data.py`, opt-in;
  `test_two_independently_trained_{lightgbm,logistic}_artifacts...` in `tests/ml/test_artifact.py`, always-on).
- **Stage 5 no-ML regression** (`tests/pipeline/test_stage5_no_ml_regression.py`, 9 tests): `Stage5Pipeline`
  with `ml_filter=None` reproduces the exact committed Stage 5 decision history, signals and `result_hash` —
  confirmed on the full `tests/pipeline tests/decision tests/regime tests/strategies tests/risk` suite too
  (191 passed, 4 skipped, unchanged from before Stage 6).
- **Full suite:** **1523 passed, 13 skipped** in ≈254 s (skips are all opt-in real-data checks — up from 8
  skips at the Stage 5 commit because the one `arven.ml`-doesn't-exist-yet static check now runs for real).
  All 13 pass together with `ARVEN_REAL_DATA_TESTS=1` (≈123 s): the original 7 (Stage 3/4/5) plus 6 new Stage
  6 real-data checks (both model families: train+verify, determinism, sealed-test refusal, honest
  insufficient-data reporting).

**Real development+validation data results** (`config/ml.yaml` + repo Stage 3-5 configs, git `2298e5a` +
Stage 6 working tree, `touched_test_set=false` on every training run and backtest below):
- **Dataset:** 7 572 raw candidates → 350 rejected by non-portfolio-state risk rules, 26 unresolvable labels
  (horizon past stored data) → **7 196 eligible** (4 790 train rows before the development/validation split,
  2 406 calibration rows in validation). This is far healthier than the pessimistic "a few thousand" planning
  estimate, precisely because D3 evaluates every candidate independently of the single capital path a real
  backtest follows (which only produced 111 trades over the same period).
- **Walk-forward:** 17 chronological expanding-window folds (3-month retrain interval, 12-month minimum
  training window, 96h embargo); logistic regression evaluated 51 fold×hyperparameter combinations (3
  configs), LightGBM evaluated 68 (4 configs); best config selected by mean fold validation log-loss.

  | model | selected hyperparameters | raw val. log-loss | calibrated val. log-loss | raw val. ROC-AUC | calibrated ECE |
  |---|---|---:|---:|---:|---:|
  | logistic | `l2=10.0` | 0.634 | 0.623 | 0.518 | ≈0 |
  | lightgbm | `num_leaves=15, max_depth=4, lr=0.03, min_data_in_leaf=30, feature_fraction=0.7, bagging_fraction=0.7, l1=1.0, l2=1.0` | 0.630 | 0.788 | 0.538 | 0.032 |

  LightGBM's calibrated log-loss is *worse* than its raw log-loss — traced to a single 36-sample calibration
  bin that isotonic regression pinned to exactly `p=0.0` despite a 41.7% actual positive rate in that bin: a
  genuine small-edge-bin isotonic failure mode (confirmed not a `_pava` bug via separate hand tests), reported
  honestly rather than silently discarded or worked around.
- **Backtest A/B** (`arven backtest run --provider pipeline --period development`, real database, same
  period as the Stage 5 baseline above):

  | run | trades | total_return | max_drawdown | win_rate | profit_factor | sharpe |
  |---|---:|---:|---:|---:|---:|---:|
  | Stage 5 only (no ML) | 111 | −20.3% | 20.6% | 33.3% | 0.566 | −1.43 |
  | + logistic MetaFilter (`threshold=0.50`, selected — see the threshold-selection note below) | 44 | **+9.0%** | 2.8% | 54.5% | 1.730 | 0.81 |
  | + LightGBM MetaFilter (`threshold=0.50`, fallback selection — see below) | 0 | 0% | 0% | n/a | n/a | n/a |
  | + shuffled-label logistic control | 0 | 0% | 0% | n/a | n/a | n/a |
  | + random filter, matched to the logistic model's ≈98% empirical reject rate | 77 | −15.1% | 20.2% | 28.6% | 0.579 | −1.13 |

  **Threshold selection (Stage 6 pre-commit audit's BLOCKER 2 fix, implemented 2026-09-29):** the threshold is
  no longer a hardcoded config default — `arven.ml.train.select_threshold` genuinely selects it from
  `config/ml.yaml`'s 5 fixed candidates (`[0.50, 0.55, 0.60, 0.65, 0.70]`) by maximizing precision
  `P(label=1 | p≥threshold)` on validation-period predictions only, restricted to candidates with ≥20
  validation rows passing (never optimizing Sharpe/return/drawdown, never touching the sealed test period,
  never depending on this table's own backtest result — selection happens once, at training time, before any
  backtest using the model is ever run). On real data: logistic's candidates 0.50–0.65 are **exact ties**
  (28 rows, precision 0.679 each — the isotonic calibrator's step function has no achieved value strictly
  between them); the lowest tied candidate (0.50) wins by the documented tie-break rule. Candidate 0.70 has
  a higher precision (0.75) but only 4 rows — correctly excluded by the coverage floor. LightGBM's every
  candidate has 0 validation rows passing (its calibrated scores never reach even 0.50), so it falls back to
  the smallest candidate, honestly flagged `used_fallback=true` in its manifest — its 0-trade backtest result
  is unchanged by this fix, for the same underlying calibration-quality reason documented above.

  The LightGBM filter and the shuffled-label control both reject essentially everything (the poorly-calibrated
  LightGBM scores never reach 0.55; the shuffled-label model, as intended, learned nothing so its scores are
  also below threshold) — 0 trades in both cases, so no trade statistics are meaningful for them. The
  matched-rate random filter (same ≈98% reject rate as the real logistic model, but rejecting *at random*
  rather than by score) still loses money (−15.1%) though less than the unfiltered baseline (fewer trades ⇒
  less cost exposure) — worse than the trained logistic model's result on every metric. This is a **single
  run on one development-period slice**, not a validated edge: it is reported as suggestive, single-run
  evidence that the logistic filter's score carries real information beyond "trade less often," consistent
  with CLAUDE.md's rule against claiming or implying guaranteed profitability. The 111→44 trade drop for the
  real model on a real backtest (vs the model passing 143 of 7 196 dataset rows, ≈98.01% rejection) reflects
  portfolio-state risk vetoes that only apply in the real one-position-at-a-time backtest, not in dataset
  construction (D3) — expected, not a bug.
- **Methodological limitation, found by the Stage 6 pre-commit audit (2026-09-29): the A/B comparison above
  conflates two distinct mechanical effects, and neither Stage 5's risk parameters nor the drawdown halt were
  changed to investigate this.** Instrumenting `Stage5Pipeline.history` directly (not just the trade ledger)
  shows the Stage 5-only baseline's `max_drawdown_halt` circuit breaker (risk rule 7, unmodified) fired for
  **4 358 of its 5 037 risk vetoes (86.5%)**, and **all 111 of its executed trades occurred in 2020** — zero
  trades in 2021, 2022, or the first half of 2023, because the 20%-drawdown halt (which only releases once
  drawdown recovers to ≤15%) was never satisfied again for the rest of the development period. The
  logistic-filtered run's 44 trades are spread across the whole period (2020: 7, 2021: 17, 2022: 10, 2023: 10)
  because it never triggered a sustained drawdown in the first place. **The observed −20.3% vs +8.6%
  difference therefore combines (a) trade-selection effects from the meta-filter and (b) a different
  interaction with the existing portfolio risk circuit breakers — not filtering-quality alone** — and the two
  are not separated in the table above. This is not evidence the logistic filter "wins" or "beats" the
  baseline; it is a description of what mechanically produced the two numbers. Separating these two effects
  (e.g., measuring the same filter's effect starting from a portfolio that never breached the drawdown halt)
  was not attempted here and would need its own controlled comparison, not a parameter change to Stage 5.
- **Model artifacts on disk:** `data/models/logistic-20260929T104905Z-50c98444/`,
  `data/models/lightgbm-20260929T104943Z-50c98444/` (both `arven ml verify`-clean, post-BLOCKER-1/2/3-fix); a
  shuffled-label control model and various earlier exploratory/pre-fix runs are also present, all gitignored
  (`/data/` root-anchored rule).

**Known limitations, all deliberate MVP scope or honestly-reported findings (not bugs)**
- **The A/B table's −20.3%/+8.6% comparison combines trade-selection and circuit-breaker effects** (see the
  methodological-limitation bullet above) — not interpreted as proof either model "wins."
- LightGBM's isotonic calibration underperforms on this dataset size (see above) — the model is trained,
  saved, and verifiable, but its backtest result (0 trades) is not usable as-is; a larger dataset, fewer
  calibration bins, or Platt scaling as a fallback are the natural next steps, not attempted here (no
  hyperparameter/calibration-method search against real-data results, per the "no sealed-test optimization,
  no manufacturing samples" instruction — and this is development+validation, not even the sealed test).
- All A/B and control results are a **single run over one fixed period** — no repeated-seed distribution
  exists for the ML-filtered backtests (unlike Stage 4's baselines, which use many seeded runs). Multiple
  seeds/periods would strengthen the evidence but were not requested for Stage 6.
- The diagnostics described in planning (SHAP summaries, calibration reliability diagrams, per-regime/
  per-strategy `P(success)` breakdowns) are computed and printable via the existing metrics functions and
  LightGBM's native Tree-SHAP, but are not yet formalised as a saved report artifact the way
  `arven.reports.per_regime_breakdown` is for Stage 5 — left for a follow-up, not blocking Stage 6 review.
- The A/B comparison above was produced by four separate `arven ml train`/`arven backtest run` invocations,
  not a single reusable `arven ml` subcommand — also left for a follow-up.

## Stage 7 — walk-forward evaluation (WFO)

**What was built:** `src/arven/wfo.py` (pure functions, no I/O) and `src/arven/wfo_runs.py` (the composition
root, mirroring `runs.py`/`ml_runs.py`) answer the question Stage 6's own limitations section raised: *does
the single-run +8.6% result hold up if measured independently, many times, across time?* WFO re-evaluates
Stage 5 (baseline) and Stage 6 (MetaFilter) **causally, window by window**, over the real 17-window
expanding-window schedule Stage 6 already uses — not a new calendar, not a new model, not a parameter search.
`cli.py` gained two additive subcommands: `arven wfo run` (executes the full schedule, both model families)
and `arven wfo show <run_id>` (prints a stored report). No existing Stage 0–6 file's logic changed.

**Methodology**
- **Schedule:** the exact, unmodified `arven.ml.splits.generate_folds(dev.start, val.end, min_train_months=12,
  retrain_interval_months=3)` Stage 6 already uses — **17 windows**, expanding, over 2020-01-01 → 2025-01-01
  (development ∪ validation only; the sealed test period, 2025-01-01 onward, is never resolved — see
  "Leakage protection" below). `MINIMUM_WINDOWS = 12`: `run_stage7` raises `InsufficientWindowsError` rather
  than silently reporting a distribution from too few windows (not hit on the real schedule: 17 ≥ 12).
- **Causal hyperparameter selection (the central design point):** for evaluation window `N`,
  `select_hyperparameters_causally` calls Stage 6's own `run_walk_forward` restricted to `folds[:N]` — every
  fold *strictly before* `N`, never `folds[N]` itself. Window 0 has no preceding fold, so it falls back to
  `hp_grid[0]` (`run_walk_forward`'s own existing empty-fold behaviour, not a new special case).
- **Causal calibration/threshold selection:** `fit_window_model` fits the model on
  `purge_and_embargo_train_mask(fold N)` **minus** a calibration block, then calibrates (isotonic, D6) and
  selects a threshold (from the same 5 fixed candidates Stage 6 uses) on that calibration block — the union of
  `validation_mask` over the **last `CALIBRATION_LOOKBACK_FOLDS = 4` folds strictly before `N`** (capped, not
  padded, when fewer than 4 preceding folds exist). Training and calibration rows are disjoint by
  construction. Requires `window_index >= 1`; returns `None` for window 0 and for any degenerate split
  (fewer than 2 label classes on either side) — reported honestly via `ml_skip_reason`, never hidden.
- **Why a 4-fold calibration lookback, not 1:** a single preceding fold (~150–250 rows) was found, during this
  stage's own pre-commit audit, to be too small for stable isotonic calibration (PAVA collapses scores toward
  the block's base rate, so almost nothing crosses even the most permissive threshold). Widening to 4 folds is
  a purely statistical fix — same method (isotonic), same threshold candidates, still strictly prior to `N`.
- **Corrected causal design, 2026-10-01 (superseded before any commit):** the first implementation selected
  hyperparameters from **all 17 folds** (window `N`'s own held-out loss contributed to the hyperparameters
  then evaluated on it) and calibrated/thresholded each window **on its own labels**. Both were found and
  fixed during this stage's own development, before being run on real data or committed — see
  `tests/wfo/test_wfo_causality.py` for the regression tests this directly enables (perturbing window `N`'s
  own rows provably does not change its hyperparameters or its fitted model; perturbing the legitimate prior
  calibration source provably *does* change them, proving the invariance tests are meaningful, not vacuous).
- **Fold 10 (the one dev/validation-boundary-crossing window):** confirmed by test to be the *only* one of the
  17 folds whose evaluation block straddles the 2023-07-01 development/validation config boundary. A single
  `SplitGuard`-resolved `AllowedWindow` cannot cross a period boundary by design, and splitting this one window
  into two separately-initialized sub-backtests was considered and rejected (it would require inventing an
  equity-chaining rule the specification never asked for, for one edge case). Fold 10 is therefore **excluded
  from backtesting only** — it stays in the schedule and still contributes to later windows' causal
  hyperparameter-selection history, since that role needs no `SplitGuard` window. Net effect: **17 windows
  generated, 16 backtested, 15 with any ML-vs-baseline comparison** (window 0 is baseline-only).
- **Leakage protection:** `tests/leakage/test_wfo_leakage.py` mirrors the Stage 6 pattern exactly — a static
  source scan proves the literal `BacktestPeriod.TEST` and `allow_sealed` never appear in `wfo.py`/
  `wfo_runs.py`; `resolve_window_for_fold` is proven to return `None` (never resolve `TEST`) even for a fold
  constructed to fall entirely inside the sealed period; a direct `SplitGuard.resolve(TEST)` call still raises
  `SealedAccessError` (belt-and-suspenders, unmodified `SplitGuard`); and the real 17-fold schedule is proven
  to never extend past `validation.end_ms` (the sealed period's start).
- **Reuse, not reimplementation** (`tests/wfo/test_wfo_static_rules.py`): `wfo.py`/`wfo_runs.py` import
  `generate_folds`, `purge_and_embargo_train_mask`, `validation_mask`, `select_threshold`, `fit_isotonic` and
  `run_walk_forward` from their existing Stage 6 modules — none are redefined locally. Neither file imports
  `arven.backtest.execution`/`accounting` or `duckdb` directly. `wfo_runs.py` imports and runs the real
  `Stage5Pipeline`, never a copy. One-directional dependency: no Stage 3–6 package imports `arven.wfo`.
- **Per-window variants:** each backtested window runs (a) the Stage-5-only baseline (no filter), and for each
  model family — logistic and LightGBM — (b) the real causally-fit MetaFilter, (c) a shuffled-label control
  (labels permuted independent of time; same causal fitting procedure, D20's existing technique), and (d) a
  matched-rate `RandomFilter` control seeded to the real filter's own empirical reject rate for that window.
- **Determinism:** schedule generation and per-window model fits are deterministic for fixed inputs (tested);
  LightGBM reuses Stage 6's `deterministic=True, force_row_wise=True, num_threads=1` fixed-seed settings.

**Validation**
- **36 new tests**, all passing: `tests/wfo/` (32: schedule, static rules, causality/perturbation, determinism,
  fit/calibration-lookback, backtest window resolution incl. the real fold-10 check and a regime-hysteresis-
  reset-across-windows check) + `tests/leakage/test_wfo_leakage.py` (4).
- **Full suite: 1565 passed, 13 skipped** (same opt-in real-data skips as before Stage 7; no regressions
  anywhere in Stages 1–6), ≈7 minutes.
- No implementation bug was found during review of the *committed* design (the causal-selection and
  calibration-lookback issues above were found and fixed during this stage's own development, before the real
  run or any commit — see the corrected-design note above).

**Real development+validation data run** (`arven wfo run`, git `e9b7c72` + Stage 7 working tree,
`touched_test_set=false`, seed 42, run `wfo-20261001T075132Z-50c98444`, 2m26s wall time, artifacts in
`data/wfo/wfo-20261001T075132Z-50c98444/`):

| | windows generated | backtested | boundary-excluded | with ML comparison |
|---|---:|---:|---:|---:|
| Schedule | 17 | 16 | 1 (fold 10) | 15 (window 0 is baseline-only) |

*Trades (sum over backtested windows):*

| Variant | Total trades | Mean/window |
|---|---:|---:|
| Baseline (Stage 5 only) | 1281 (16 windows) | 80.1 |
| Logistic MetaFilter | 25 (15 windows) | 1.67 |
| LightGBM MetaFilter | 29 (15 windows) | 1.93 |
| Logistic shuffled-label control | 20 | 1.33 |
| LightGBM shuffled-label control | 0 | 0 |
| Logistic matched-rate random control | 47 | 3.13 |
| LightGBM matched-rate random control | 72 | 4.80 |

Both real filters reject ≈97–98% of candidates per window (consistent with Stage 6's single-run finding, now
shown across 15 independent windows rather than one).

*Performance (mean across backtested windows):*

| Metric | Baseline (n=16) | Logistic ML (n=15) | LightGBM ML (n=15) |
|---|---:|---:|---:|
| total_return | **−11.22%** (range −3.1% to −20.5%, negative in **every** window) | −0.08% (median 0.0%) | −0.10% (median 0.0%) |
| net_pnl (USDT, per-window fresh $10k) | −1121.96 | −7.98 | −9.81 |
| max_drawdown | 13.8% | 0.76% | 0.72% |
| sharpe | −3.54 | +0.49 (n=6 non-null) | −0.54 (n=7 non-null) |
| win_rate | 32.6% | 43.2% (n=7) | 38.7% (n=7) |
| raw ROC-AUC (classification, all 15 windows) | — | 0.42–0.55 | 0.44–0.60 |

**Key finding: Stage 6's single-run "+9.0% / logistic MetaFilter, −20.3% baseline" result does not replicate
under genuine walk-forward evaluation.** Two things are now shown with much stronger evidence than Stage 6's
one continuous backtest could provide:
1. **The unoptimized Stage 5 strategies have no edge, consistently**, not just in one 3.5-year run: the
   baseline loses money in every one of the 16 independently-evaluated, independently-capitalized ~3-month
   windows across 2021–2025. This also rules out the Stage 5/6 single-run result being an artifact of the
   `max_drawdown_halt` circuit breaker getting stuck after 2020 (each WFO window starts with fresh portfolio
   state, so there is no multi-year halt to get stuck in).
2. **Neither MetaFilter shows real discriminative skill**: raw ROC-AUC sits in a tight ~0.42–0.60 band in
   *every* window for *both* model families — indistinguishable from chance. This fully explains both the
   ~98% rejection rate and why the filtered mean return is flat (≈0%) rather than positive.

**Weaknesses and anomalies found (reported honestly, not tuned away)**
- **LightGBM's isotonic calibration is unstable in most windows**, not just the single case Stage 6 flagged:
  calibrated log-loss is *worse* than raw in several windows (e.g. window 7: 0.618→1.742; window 13:
  0.639→2.684) — the same small-sample isotonic-overfit failure mode, now shown recurring across the majority
  of the 15 causal windows rather than appearing once.
- **The logistic shuffled-label control shows a spurious positive mean return** (+0.27%, +$408 total) purely
  from sampling noise: only 4 of 15 windows produced any trades at all under the shuffled model, and one
  window's 11 trades dominate the mean. This is far smaller and far less consistent than the baseline's
  reliably negative signal, and the dedicated perturbation tests already prove the causal mechanism does not
  leak — it is noted here so the number isn't misread as evidence of a leak when reviewing the raw report.
- **Most per-variant distribution statistics (sharpe, profit_factor, win_rate) are built from only 4–7 of the
  15 windows**, because most windows produce zero ML-filtered trades. The report records each metric's own `n`
  (`arven.backtest.metrics.summarize_distribution`); these are not well-powered distributions and should not
  be read as one when cited.
- **Fold 10's exclusion removes one quarter (2023 H2) entirely** from the backtested evidence, baseline
  included — a real, small, and intentional coverage gap (see "fold 10" above).
- Window 0 (2021 Q1) has no ML comparison by construction (no preceding fold to calibrate on) — expected, not
  a defect.

**Known limitations, all deliberate MVP scope or honestly-reported findings (not bugs)**
- This is a single real-data run with one fixed random seed, same as Stage 6's own A/B table — no repeated-
  seed distribution across WFO runs exists (the within-run, across-window distribution above is a different,
  complementary kind of evidence, not a substitute).
- No saved report artifact beyond the one `report.json` per run yet; no dashboard/plot of the per-window
  trajectory — `arven wfo show <run_id>` prints the stored JSON, nothing more polished, left for a follow-up.
- The real run was only executed once (not re-run for a second determinism check on real data, though
  `tests/wfo/test_wfo_determinism.py` and Stage 6's own determinism precedent cover this at the unit level).

## Stage 8 — the paper-signal loop

**What was built:** `src/arven/paper/` (composition root), `src/arven/data/adapters/binance_rest.py` (a new
public-REST client) and `src/arven/data/rest_ingestion.py` (the REST-tail counterpart of Stage 2's bulk
loader), plus a new `BacktestPeriod.FORWARD` in `core/splitguard.py`. The headline design result: **no new
execution or decision logic was needed anywhere** - two things already in place from earlier stages made
this possible. `backtest.clock.Clock` was always a `Protocol`, documented since Stage 4 as "a live loop
implements the same protocol with real time, so backtest and live share one code path". And
`features.builder.build_features` was always documented (Stage 3) as serving "the live loop (one decision
time, on inputs truncated with `MarketInputs.available_until`)". Stage 8 is therefore almost entirely data
plumbing: it REST-updates the database and feeds the *unmodified* `Backtester`/`Stage5Pipeline` a new kind of
period.

**The forward period**
- `BacktestPeriod.FORWARD` resolves `[splits.forward_start, end_ms)`, where `end_ms` is supplied explicitly
  by the caller (there is no fixed upper bound to default to, unlike development/validation/test) - `SplitGuard`
  itself still never reads the wall clock; only `arven.paper` ever computes "now" (one read per tick, via
  `core.timeframes.last_closed_bar_open`, the same point-in-time rule Stage 2/3 already use for bar
  availability). FORWARD is never sealed: there is no future beyond "now" to leak, so nothing here needs
  acknowledgement or logging, and it cannot be used to reach backward into development/validation/test (a
  range crossing into an earlier period is refused, exactly like every other period).
- `docs/architecture.md`'s own "Data periods" table already listed "2026-07 -> onward: Forward paper-trading"
  as a fourth row from the start - Stage 8 implements that row, not a new design decision.

**REST-tail updates** (`data/adapters/binance_rest.py`, `data/rest_ingestion.py`)
- Public Binance USDⓈ-M futures REST endpoints only (`/fapi/v1/klines`, `/fapi/v1/fundingRate`) - no API key,
  no account/order endpoint is ever referenced (enforced by a static test; CLAUDE.md rule 12). `RestIngestor`
  writes into the exact same `ohlcv_1m`/`funding_rates` tables the bulk pipeline uses (one market-data
  history, not a separate "live" copy), continuing from whatever is already stored - it is a *tail* updater,
  not a historical backfill tool (that remains `arven ingest`'s job).
- **Open interest / top-trader / taker long-short ratios are not REST-updated** (Stage 8 scope decision):
  these are the same optional, NaN-tolerant feature group Stage 3 already handles for any other data gap
  (`oi_available`), so they simply go stale for the forward period rather than gaining new live-fetch code.
- **A real performance bug was found and fixed before this was usable**: the first implementation wrote REST
  pages with `con.executemany(...)` directly into `ohlcv_1m`/`funding_rates` (both PRIMARY-KEY-indexed) -
  measured at ~33 seconds per 1000-row page (the exact "executemany into a PK ART index is pathologically
  slow" pitfall this project's own test infrastructure had already hit and documented, see "Operational
  notes" below). Catching up the real ~3-month data gap (see below) at that rate would have taken the better
  part of an hour. Fixed by switching to the same staged bulk-load idiom `ingestion.py` already uses for bulk
  files (CSV -> `read_csv` -> temp table -> one `INSERT OR REPLACE`): **0.045 s for the same 1000-row page**,
  a ~740x speedup, verified by both a direct before/after benchmark and the real catch-up run below.

**The composition root** (`paper/runs.py`, mirrors `runs.py`'s own role for Stage 4)
- `run_paper_tick`: REST-tail klines/funding up to the latest fully-closed, available 1m bar -> resample just
  the trailing window the new bars could affect (not the whole multi-year history) -> resolve the FORWARD
  window -> build that window's feature rows **in memory** with the unmodified `build_features` (Stage 3's
  persisted `data/features/<version>/` cache, and its documented content hash, is never touched - a second,
  parallel live cache would have risked exactly the kind of drift the project's reproducibility story depends
  on not having) -> run the real `Stage5Pipeline` through `runs.execute_run` **unchanged**, the identical
  function `arven backtest run` itself calls -> write a run artifact (`data/paper/<run_id>/run.json` +
  ledgers), indexed in its own `data/paper/runs.jsonl` (kept separate from `data/backtests/runs.jsonl` so
  paper runs are never mixed into the Stage 4 backtest index).
- **The "paper-trade tracker" is not new code**: every tick replays the *entire* forward history from
  `forward_start` through "now" via Stage 4's own `Simulator` (inside `execute_run`), exactly like re-running
  `arven backtest run --period forward` with a later end each time. This is simpler and safer than
  incremental state checkpointing between ticks (no serialization format to get wrong, trivially
  reproducible, and cheap at the scale a few months of 1m bars implies - the real run below took well under
  a minute for the simulation itself).
- **`arven paper run` is idempotent and catch-up capable** (its one design requirement): every invocation
  resolves `[forward_start, now)` fresh and is safe to run from Task Scheduler/cron at any cadence, by hand,
  or after a gap, without missing or double-processing a decision time - there is no per-tick state to
  corrupt, only the growing market database.

**CLI** (`cli.py`, additive only): `arven paper run [--ml-model <id> | --random-filter-rate <p>]`,
`arven paper show <run_id>`, `arven paper status`. No dashboard/Streamlit view (architecture's own A9 answer:
"CLI + persisted signal log first; optional Streamlit dashboard later").

**Module separation, enforced mechanically** (`tests/paper/test_paper_static_rules.py`): no Stage 3-7 package
imports `arven.paper` (one-directional dependency); `paper/runs.py` defines none of
`Backtester`/`Simulator`/`Stage5Pipeline` itself and never imports `arven.backtest.execution`/`accounting`
directly (it drives everything through the real `Backtester` via `runs.execute_run`); `binance_rest.py` and
`rest_ingestion.py` never reference an API-key header, a signature parameter, or any order/account endpoint
path.

**A second real bug, found by the real run itself (not by any test), before the result below was trusted:**
`update_market_data`'s first implementation resampled only a fixed 2-day lookback window after a REST tail,
on the (wrong) assumption that a tick only ever adds about an hour of new 1m data. The real catch-up below
added ~94 days in one call; the fixed lookback silently left all but the last 2 days of that range's derived
5m/15m/1h/4h bars unbuilt. The real forward run's first result, with this bug still present, showed **0
trades over 94.4 days** - surprising against Stage 7's baseline (32-106 trades per similarly-sized window in
every one of 16 historical windows, never 0) and investigated rather than accepted: a direct query found only
49 of the expected 2266 hourly bars existed for the period, and the rest were simply missing, starving every
feature after them of data (`feat_ready` could never reach 1). Fixed by resampling from a small buffer before
whatever 1m data already existed through the new data's end - the *entire* newly-tailed range, regardless of
its size - and covered by a new regression test (`test_update_market_data_resamples_the_whole_new_range_not_
just_a_fixed_lookback`) that seeds a small prior range, REST-tails nine more days (far past the old 2-day
buffer) and asserts every one of those 216 hours gets a complete derived bar. The already-corrupted real
database was repaired with the existing `arven resample` command before re-running.

**Validation**
- **32 new tests**: `tests/unit/test_binance_rest.py` (6, offline fake-opener response parsing/pagination),
  `tests/unit/test_rest_ingestion.py` (7, DB upsert correctness, idempotency, alignment/drift validation,
  continuation from an existing last-stored row), `tests/leakage/test_paper_leakage.py` (6, FORWARD never
  resolves or falls back to TEST, cannot reach backward into earlier periods, the sealed-access log is never
  touched), `tests/paper/test_paper_runs.py` (9, a full synthetic DB -> REST tail -> resample -> forward
  window -> real `Stage5Pipeline` -> written artifact round trip, plus the resample-range regression test
  above) and `tests/paper/test_paper_static_rules.py` (5, import-boundary and no-reimplementation checks).
- `tests/backtest/test_splitguard_and_loading.py` gained 8 tests for the new FORWARD branch (default end
  behaviour, explicit end required, refuses a start before `forward_start`, no upper bound, never sealed,
  needs no log, still rejects non-hour-aligned bounds, `period_bounds` does not resolve it) and lost the one
  pre-Stage-8 test that asserted FORWARD did *not* exist as a period (superseded, not just deleted - the new
  tests assert the actual behaviour instead) - a net +7 in that existing file, +32 in new files, +39 overall.
- **Full suite: 1605 passed, 13 skipped** (same opt-in real-data skips as before Stage 8; no regressions
  anywhere in Stages 1-7), confirmed after both the `executemany` performance fix and the resample-range fix
  above, and after repairing the real database.

**Real run** (`arven paper run`, live Binance REST data, run 2026-10-03; forward_start = 2026-07-01, window
`[2026-07-01, 2026-10-03T06:00)`, 94.4 days, `touched_test_set=false`):

| provider | trades | total_return | max_drawdown | sharpe | win_rate | profit_factor |
|---|---:|---:|---:|---:|---:|---:|
| Stage 5 baseline (no filter) | 89 | −14.9% | 15.8% | −4.89 | 32.6% | 0.53 |
| + logistic MetaFilter (`logistic-20260929T104905Z-50c98444`) | 2 | +0.06% | 1.1% | 0.10 | 50.0% | 1.07 |

This is the **first genuinely forward, out-of-sample evidence** the project has produced (every other result
so far is historical, however carefully split) - and it reproduces, on live data the model has never seen in
any form, exactly the pattern found throughout Stage 5-7: the unoptimized baseline strategies lose money
(consistent with all 16 of Stage 7's historical windows), and the logistic MetaFilter is flat-to-slightly-
positive on very few trades (2, well under the 30-trade statistical-meaningfulness threshold the metrics
module itself warns about) rather than reproducing Stage 6's single-run +8.6% - consistent with Stage 7's
finding that that result does not generalize. This is one 94-day sample, not a validated result either way;
it is reported as a first data point for the forward paper-trading record the thesis will keep accumulating.

**Known limitations, all deliberate MVP scope (not bugs)**
- Open interest and the top-trader/taker long-short ratios are not updated live (see above) - `oi_available`
  correctly reflects this as staleness, exactly as the policy already specifies for any other gap.
- No dashboard/Streamlit view yet - CLI only, per architecture's own stated ordering.
- Every tick replays the full forward history rather than checkpointing incrementally - simple and safe now;
  would need revisiting only if the forward period grows large enough (many years) for a full replay to
  become slow, which is not the case at the scale paper trading runs at.
- `arven paper run` must be invoked by something external (Task Scheduler, cron, or by hand) - Stage 8 does
  not add a persistent background daemon (deliberately, per the D7 design discussion: a laptop that sleeps or
  reboots would otherwise silently stop producing signals without the catch-up design being exercised).

**Operational note (2026-10-03):** an hourly Windows Scheduled Task named `ARVEN Paper Run` was registered on
the development machine (`schtasks`/`Register-ScheduledTask`, not part of this repo or any commit) running
`scripts/run_paper_tick.bat`, which `cd`s into the repo and runs `arven paper run`, appending output to
`data/paper/scheduled_run.log` (git-ignored). This is the actual, currently-running source of the forward
paper-trading record; `scripts/run_paper_tick.bat` itself *is* committed (a thin, reviewable wrapper), but
registering the task against it is a one-time local machine-setup action, same category as creating the
`.venv`.

## Stage 9a — macro calendar + risk-engine event blackout

**What was built:** `config/macro_events.csv` (a committed, researched calendar of real FOMC/CPI/NFP
schedule dates — not synthetic, not scraped, sourced directly from `federalreserve.gov`'s FOMC calendar and
`bls.gov`'s own release-schedule and news-release archive pages, 228 rows spanning 2020-01 through 2027-12,
including the real emergency March 2020 FOMC actions and the real 2025 government-shutdown reschedules),
`src/arven/core/macro_config.py` (the loader), and risk engine rule 2 in `src/arven/risk/engine.py`
(previously the one explicitly-deferred rule of the 8; all 8 now exist).

**Design**
- **Only the *scheduled* release time is used, never the eventual released value** (no CPI print, no NFP
  number, no FOMC decision outcome is stored or read anywhere). A release's scheduled time is public
  knowledge announced months to a year in advance, so using it at any decision time — including for the
  sealed test period or any historical backtest — carries no look-ahead risk, unlike a feature that would
  need the actual number. `MacroEvent` is structurally limited to `(scheduled_at_ms, event_type, note)` — no
  `actual`/`forecast` field exists to accidentally misuse (enforced by a dedicated test).
- **ET->UTC conversion is computed directly from the fixed US DST rule** (2nd Sunday of March to 1st Sunday
  of November, unchanged since 2007) rather than via `zoneinfo`: this machine's Python has no system IANA
  timezone database (Windows ships none by default), and the `tzdata` PyPI package would be a new dependency
  for a problem with exactly two, legally fixed rules — cheaper and equally correct to compute directly
  (verified against hand-picked boundary dates in both directions, `tests/unit/test_macro_config.py`).
- **Symmetric blackout window**: a release scheduled at `T` vetoes new entries for `t ∈ [T - window, T +
  window]`; `macro_blackout_window_hours` (`config/risk.yaml`, default **1.0h**) is the only new risk
  parameter. Veto-only (no "reduce" variant) — a deliberate Stage 9a scope simplification; architecture.md's
  sketch allows either, Stage 9a implements the simpler one.
- **Rule 2 sits between rule 1 (data-quality gate) and rule 7's early portfolio-state checks** in the actual
  execution order inside `RiskEngine.apply()` — both 1 and 2 are "is this decision time even usable at all"
  gates, checked before the cost-driven rule-7 block, matching the existing (non-numeric) execution order's
  own logic.
- **Additive, byte-identical-when-absent** (the same pattern Stage 6 used for `ml_filter`): `RiskEngine` and
  `Stage5Pipeline` both take `macro_events: tuple[MacroEvent, ...] = ()` as an optional constructor
  parameter. An empty tuple (the default) means rule 2 never fires — every existing caller, test, and
  previously-committed result (Stage 5, 6, 7's WFO, Stage 8's already-run paper ticks) is completely
  unaffected unless it explicitly opts in. `cli.py`'s shared `_build_pipeline` helper (used by both
  `arven backtest run --provider pipeline` and `arven paper run`) now loads the real calendar by default, so
  **new** runs of either command get the blackout; `wfo_runs.py` was deliberately left untouched (still
  passes no `macro_events`), so Stage 7's committed walk-forward results stay exactly reproducible.

**Module separation, enforced mechanically**: `core/macro_config.py` never imports `duckdb`, `arven.data`,
`arven.backtest`, or `arven.features` (a CSV-reading config loader, same tier as `risk_config.py`); the
existing Stage 5 import-boundary tests (`tests/pipeline/test_stage5_static_rules.py`) already forbid `risk`
from importing `arven.data`/`arven.features`/`duckdb`/the execution engine, and continue to pass unchanged
with the new `arven.core.macro_config` import added (not in that forbidden list — `core` is a shared,
lower-tier package every stage already depends on).

**Validation**
- **33 new tests**: `tests/unit/test_macro_config.py` (18: DST offset hand-computed against the fixed rule in
  both directions, real-calendar sort/dedup/coverage, hash determinism, the no-actual-field structural
  guarantee, an import-boundary check), `tests/leakage/test_macro_leakage.py` (3: the blackout decision is a
  pure function of `(t, calendar)` with no data input to leak, the loader takes no market/decision-time
  parameter at all), and 12 new cases added to `tests/risk/test_risk_engine.py` (exactly-at-the-scheduled-
  time, the symmetric window's boundary in both directions — both inclusive and just-outside, which event
  wins when several are nearby, blackout is checked before but does not skip the stateful circuit-breaker
  bookkeeping, a `NO_TRADE` proposal never reaches rule 2 at all, and the empty-calendar no-op case).
- **Full suite: 1638 passed, 13 skipped** (same opt-in real-data skips as always; no regressions anywhere in
  Stages 1-8 — confirmed both before wiring the new parameter through `cli.py`/`Stage5Pipeline`/`RiskEngine`
  and after, since the default `macro_events=()` keeps every existing test's behaviour byte-identical).

**Known limitations, all deliberate MVP scope (not bugs)**
- **Veto only, no "reduce"** — architecture.md's sketch allows either; Stage 9a implements the simpler of the
  two, consistent with "do not optimise/over-build beyond what's asked."
- **The calendar is a committed, point-in-time snapshot of a real, officially-sourced schedule, not a live
  feed** — it needs a manual update (appending rows to `config/macro_events.csv`) to extend past 2027-12 or
  to catch a late reschedule the official sources hadn't published yet when this was compiled (2026-10-05).
  This mirrors how the rest of the project already treats static, slow-changing reference facts (e.g.
  `qty_step_btc`/`min_notional_usdt` in `backtest.yaml`, open issue #12) — a known, documented freshness
  limit, not a silent gap.
- **One real-world gap found and documented, not hidden**: the 2025 US government shutdown (Oct-Nov 2025)
  cancelled the October-2025-reference-month CPI and Employment Situation releases entirely (confirmed from
  BLS's own shutdown-reschedule notice) — there is correctly no calendar row for that cancelled release
  (nothing to black out), and the surrounding reschedules (CPI delayed to Oct 24 and Dec 18; NFP delayed to
  Nov 20 and Dec 16) are each recorded at their *actual* (not originally-scheduled) date, since that is what
  the market actually reacted to in real time.
- Only FOMC/CPI/NFP are in scope (architecture's own named examples) - a wider macro calendar (GDP, PCE,
  ISM, etc.) was not requested and is not built.

## Stage 9b — news ingestion + LLM structuring

**What was built:** `src/arven/news/` (RSS fetch/parse, the fixed structured-output schema, the
fetch→store→structure composition root) and `src/arven/llm/anthropic_client.py` (a thin, dependency-free
Anthropic Messages API client). Two new DuckDB tables, `news_items` and `news_events`
(`data/storage/schema.py`, `schema_version` bumped to 2 — purely additive DDL, no existing table touched).
CLI: `arven news run`, `arven news show`.

**A real-world correction found while designing this stage:** the original plan (per the D-decisions
discussion) was CryptoPanic's API for news. Researching its actual current terms found that CryptoPanic
discontinued its free API tier in early 2026 — the cheapest plan is now $50/week. Reported back before
building anything against it; the news source was switched to free RSS feeds (CoinDesk, CoinTelegraph —
both verified live and fetchable during this stage's own development) instead, at the cost of noisier,
less structured input than CryptoPanic's purpose-built JSON API would have given.

**Design**
- **Forward-only by construction, not by a date check.** `src/arven/news/__init__.py`'s own module
  docstring states the rule; mechanically, the entire `news` package never imports `BacktestPeriod` or
  `SplitGuard` (enforced by a static test) and has no period/window parameter anywhere in its functions. It
  only ever processes RSS items that exist in the feed *at the moment it is run* — there is no code path
  that could point it at a historical date range, so the architecture's rule 11 (LLM training-cutoff
  contamination) is satisfied structurally rather than needing an explicit guard to get right every time.
- **The LLM only ever structures text into the fixed schema** (`news/schema.py`'s `NewsEvent`: `event_type`,
  `asset_relevance`, `direction_bias`, `severity` [0,1], `confidence` [0,1], `summary` [≤280 chars]) — never
  a trading decision, indicator, price, size, or PnL (CLAUDE.md rule 9). `extra="forbid"` on the pydantic
  model means an LLM response with any extra field is rejected, not silently accepted with unused data.
- **A malformed or non-JSON LLM response is recorded, not discarded or retried indefinitely**:
  `news.schema.parse_llm_response` raises a typed `NewsEventParseError` (tolerating markdown code fences,
  since models sometimes add them despite being told not to), and the composition root stores the raw
  response text plus the parse error in `news_events` with `event_type IS NULL` — an honest, inspectable
  failure record, matching the project's "report don't hide" culture elsewhere (e.g. Stage 6's LightGBM
  calibration finding).
- **Cost control is a config value, not a runtime guess**: `max_items_per_tick` (`config/news.yaml`,
  default 10) hard-caps how many LLM calls one `arven news run` invocation makes, regardless of how many
  new RSS items arrived; the remainder simply wait for the next invocation (oldest-first, by `published_at`).
- **Idempotent, like every other tick-based command in this project**: items are deduplicated by
  `news_id = sha256(source, url)`; a `(news_id, llm_model, prompt_version)` row is never re-created once it
  exists, so changing the model or the prompt naturally produces new, comparable rows alongside the old
  ones rather than overwriting history.
- **No new HTTP-client dependency**: the Anthropic Messages API is a single JSON POST with two headers
  (`x-api-key`, `anthropic-version`) — called via stdlib `urllib.request` directly, the same choice already
  made for Binance REST in Stage 8, rather than adding the official `anthropic` SDK. The only genuinely new
  dependency is `python-dotenv` (for reading `ANTHROPIC_API_KEY` from a local `.env`) — already present in
  this project's `.venv` as a "pre-existing package," now made an explicit, declared dependency in
  `pyproject.toml` rather than an undeclared accident.
- **RSS, not a feed-parsing library**: stdlib `xml.etree.ElementTree` plus `email.utils.parsedate_to_datetime`
  (RFC-822 `pubDate` parsing) are sufficient for RSS 2.0's `<item><title>/<link>/<pubDate>` shape; an item
  missing any of the three required fields, or with an unparseable `pubDate`, is skipped, never guessed.

**Module separation, enforced mechanically** (`tests/news/test_news_static_rules.py`): `news`/`llm` never
import `decision`/`risk`/`strategies`/`regime`/`backtest`; no package in `regime`/`strategies`/`risk`/
`decision`/`features`/`ml`/`backtest`/`paper` imports `news`/`llm` (one-directional — nothing reads
structured news output yet, by design); `news` never imports `SplitGuard` or references `BacktestPeriod`;
`llm/anthropic_client.py` never references an order/account endpoint.

**Validation**
- **40 new tests**: `tests/llm/test_anthropic_client.py` (6: response parsing, retry on 5xx, no retry on
  401/403, the no-silent-default missing-API-key guarantee, multi-block text concatenation),
  `tests/news/test_rss.py` (6: real-shaped RSS fixtures, stable content-independent `news_id`, missing-field
  and unparseable-date skipping, timezone-offset conversion), `tests/news/test_schema.py` (12: valid/invalid
  LLM output, markdown-fence tolerance, every schema-violation case raising rather than coercing),
  `tests/news/test_runs.py` (5: fetch→store→structure end to end against fakes, idempotent re-run, the
  cost-control cap, malformed-response recording, `available_at` never earlier than ingestion),
  `tests/news/test_news_static_rules.py` (4, listed above), `tests/news/test_news_config.py` (7:
  hash stability/sensitivity, invalid-config rejection - same pattern as `test_risk_config.py`).
- **Full suite: 1678 passed, 13 skipped** (same opt-in real-data skips as always; no regressions anywhere
  in Stages 1-9a).
- **Not yet validated against the real Anthropic API** — no `ANTHROPIC_API_KEY` was available in this
  session. Everything above is tested against scripted fake HTTP responses only (mirroring exactly how
  Stage 8's REST adapter was tested before its own first real run). This is an explicit, acknowledged gap,
  not an oversight: the user chose to proceed without a real smoke test for now.

**Known limitations, all deliberate MVP scope or honestly-reported findings (not bugs)**
- **No real LLM call has been made.** The structured-output schema, the retry logic, and the cost cap are
  all exercised only against scripted responses. A real call could behave differently in ways fakes cannot
  catch (e.g. the model's actual tendency to follow the JSON-only instruction) — `parse_llm_response`'s
  honest-failure-recording design exists specifically because this was anticipated, but it has not been
  observed on a real response yet.
- **RSS instead of CryptoPanic**: noisier and less structured than a purpose-built news API would have been
  (no built-in sentiment/importance tagging, no currency filter) — the LLM structuring step exists
  precisely to compensate for this, but was itself not validated against real output (see above).
- **Not wired into any feature, risk rule, or decision** — structuring is the entire scope of this stage;
  deciding how (or whether) a `NewsEvent` should influence anything downstream is a separate, later
  integration decision, deliberately not made here.
- **Not added to the hourly Windows Scheduled Task** — `arven news run` must be invoked manually (or
  scheduled separately by the user) so that LLM API costs are never incurred without an explicit decision
  to do so.
- Only two RSS sources (CoinDesk, CoinTelegraph) — both confirmed live during development; more could be
  added to `config/news.yaml`'s `feeds` map with no code change.
- `news_events`'s `summary` field is capped at 280 characters (a deliberate bound, not a found limitation)
  to keep stored rows small and because this stage has no downstream consumer that would need more.

## Stage 10 — LLM explanations/Q&A + Streamlit dashboard

**What was built:** two independent pieces, both read-only over already-computed data.

1. **Explanations and Q&A** (`src/arven/llm/explain.py`, `src/arven/llm/context.py`,
   `src/arven/llm/qa.py`, `src/arven/core/explain_config.py`, `config/explain.yaml`). CLI: `arven explain
   <run> [--index N]`, `arven ask "<question>"`.
2. **Streamlit dashboard** (`src/arven/dashboard/`), the A9/Stage-8-deferred UI. CLI: `arven dashboard`
   (wraps `streamlit run` as a subprocess).

**Design**
- **`reports.decision_summary()`** turns one `DecisionRecord` (regime, every candidate, the proposed
  action, risk outcome) into a plain JSON-safe dict - the fixed, already-computed payload an LLM is later
  given to explain, never to recompute (CLAUDE.md rule 9). `paper.runs._write_decision_history()` writes one
  `decisions.jsonl` line per decision time alongside every paper run's existing artifacts, duck-typed on
  `provider.history` so `paper/runs.py` stays provider-agnostic (a provider with no `.history`, e.g. the
  `NoTrade` baseline, simply gets no file - exercised by test, not assumed).
- **The LLM only ever writes prose from data it is handed, never a new number.** `explain_decision()` sends
  one `decision_summary()` payload and a system prompt that forbids suggesting a different action,
  predicting the future, or recommending a trade - it is structurally unable to overrule the real decision
  because the decision already happened before the LLM is ever called. `answer_question()` is told to
  answer only from the context block it is given and to say so plainly when that context does not cover the
  question - **this is a weaker guarantee than the rest of the project's point-in-time/leakage guarantees**
  (there is no further structural gate like `news.schema`'s fixed-schema validation on the output), and
  `llm/qa.py`'s own module docstring says so explicitly.
- **`llm.context.build_context()` reads only artifacts earlier stages already wrote**: the latest paper
  run's manifest/metrics and its `decisions.jsonl` (`llm.context.load_latest_paper_context`), plus the most
  recent structured news rows (`llm.context.load_recent_news`, a left join of `news_items`/`news_events`).
  Nothing here is computed fresh. A real bug was found and fixed while testing this against a fresh config
  with no database file yet: `load_recent_news` called `duckdb.connect(..., read_only=True)` without
  checking the file exists first, raising an unhandled `IOException` on the very first `arven ask` before
  any `news`/`paper`/`backtest` run had ever created it - fixed to return `[]` in that case (missing data
  stays a safe, empty result, never a crash, matching the project's NO_TRADE-default culture elsewhere).
- **Cost control stays explicit.** `config/explain.yaml` uses `claude-sonnet-5-5` (more capable than Stage
  9b's classification-sized Haiku, since this is low-volume and user-triggered rather than per-item) with
  separate `max_tokens_explain`/`max_tokens_qa` caps. The dashboard's explain/Q&A sections only ever call the
  LLM on an explicit button press - never on page load or on every rerun - so opening the dashboard never
  spends API budget by itself.
- **The dashboard is a presentation layer, not a new module in the stage-separation sense.**
  `src/arven/dashboard/__init__.py`'s own docstring states why it is exempt from the rules the packages
  below it must follow: it has no write path into the market database, no decision/risk/strategy logic of
  its own, and cannot trigger a backtest, a paper tick, or a real order (CLAUDE.md rules 7, 9, 12).
  `dashboard/data.py` is pure I/O (`list_runs`, `run_dir_for`, `load_manifest`, `load_csv`,
  `load_decisions` - no `streamlit` import, so it is unit-testable without a display) and
  `dashboard/app.py` is the actual Streamlit script: three tabs for paper (forward) runs and backtest runs
  (manifest metrics, equity curve, trades table, and - paper runs only - the decision history with a
  per-decision "explain" button), a news tab, and an "ask" chat tab. `arven dashboard` launches it via
  `python -m streamlit run ... ` as a subprocess rather than any new application code, the same relationship
  `pytest` already has to this project.
- **New dependencies**: `pandas` and `streamlit` (which pulls `pyarrow`, `altair`, `pydeck`, and about 20
  smaller packages - see "Environment" below). The install itself needed several long retries over a very
  slow connection on this machine (the same connection-reset pattern already seen for `numpy` in Stage 3 and
  `lightgbm` in Stage 6, this time slow trickling rather than resets); the final attempt completed in well
  under a minute once most packages were already cached from the earlier partial attempts.

**Module separation, enforced mechanically**: `tests/news/test_news_static_rules.py`'s existing
`(SRC / "llm").rglob("*.py")` scan already covers the three new `llm/` files with no change needed -
`explain.py`, `context.py`, and `qa.py` still never import `decision`/`risk`/`strategies`/`regime`/
`backtest`. `dashboard/` is deliberately outside that scan (see "Design" above for why it is exempt).

**Validation**
- **30 new tests**: `tests/test_reports.py` (+2: `decision_summary` serialises every field, including the
  `ml_filtered`/veto case), `tests/paper/test_paper_runs.py` (+2: `decisions.jsonl` is written from the real
  pipeline's own history and is absent for a provider without one), `tests/llm/test_explain.py` (1),
  `tests/llm/test_qa.py` (1), `tests/llm/test_llm_context.py` (7, incl. the missing-database-file regression
  above), `tests/llm/test_explain_config.py` (8, same hash-stability/invalid-config pattern as
  `test_news_config.py`), `tests/dashboard/test_data.py` (9).
- **Full suite: 1708 passed, 13 skipped** (no regressions in Stages 1-9b).
- **The dashboard script itself was smoke-tested against this machine's real local data** (16 real paper
  runs, 20 real backtest runs): launched headlessly via `streamlit run` (HTTP 200, `/_stcore/health` ok, no
  exceptions in the server log) and separately executed directly with `runpy` to force every line of
  `app.py`'s own logic (not just the server's static shell) to run against the real `data/paper`/
  `data/backtests` artifacts - confirmed to complete with no exception. A `use_container_width` deprecation
  warning surfaced during this smoke test and was fixed (`width="stretch"`) before commit.
- **Not yet validated against the real Anthropic API** - same acknowledged gap as Stage 9b, for the same
  reason (no API key available in this session). `explain_decision`/`answer_question` are tested only
  against a scripted fake `complete()`.

**Known limitations, all deliberate MVP scope or honestly-reported findings (not bugs)**
- **No real LLM call has been made** for explanation or Q&A either - see "Validation" above.
- **The Q&A system prompt is the only guardrail against off-scope answers** - unlike `news.schema`'s
  pydantic validation, there is no structural check that an answer actually stayed within the given
  context. Acceptable for a research/explanation tool, explicitly documented as weaker than the rest of the
  project's guarantees (see "Design" above).
- **The dashboard has no authentication or access control** - acceptable for a single-user local research
  tool run with `streamlit run`/`arven dashboard` on one laptop, not suitable for any shared deployment.
- **No caching** (`st.cache_data`) on the dashboard's file/DB reads - every rerun re-reads from disk. Not a
  problem at this project's data scale (a few thousand decisions, a few dozen runs); a candidate for later
  if the dashboard ever feels slow.
- **Decision history is paper-run-only** - backtest runs do not persist `decisions.jsonl` (`execute_run`
  itself did not change; only `paper.runs.run_paper_tick` calls the new `_write_decision_history` helper),
  since the explain/Q&A features are framed around the live/forward loop, not historical backtests.

## Signal-product build-out (`docs/ARVEN_MASTER_PROMPT.md`)

A separate, larger initiative approved by the owner after Stage 10: turn ARVEN into a usable signal
product (multi-timeframe event-driven engine, a new strategy, Telegram alerts, a web dashboard) while never
breaking the thesis-core pipeline above. Tracked as its own phase sequence (master prompt section 6, 12
phases); this section is updated at the end of each phase the same way the Stage sections above are.

**Phase 0 — safety net (done, 2026-10-07).** Tag `pre-signal-product` on the Stage-10 head (`b9b28e8`, which
also carries the master-prompt doc itself); new branch `feat/signal-product`. Golden regression
(`tests/pipeline/test_stage5_no_ml_regression.py`) green; golden `result_hash 3eca0a70...` confirmed present
in real local backtest artifacts, matching "Stage 5" above. Full suite baseline recorded: 1708 passed/13
skipped - exactly the count the master prompt itself names.

**Phase 1 — `StrategySpec`/`BarCloseEvent`/`EventClock` (done, 2026-10-07).** New package `src/arven/engine/`
(`spec.py`, `events.py`, `clock.py`), deliberately isolated from the legacy stack - it imports only
`arven.core` (timeframes/time), never `decision`/`risk`/`strategies`/`regime`/`backtest` (enforced by
`tests/engine/test_engine_static_rules.py`, the same static-AST pattern as `tests/news/test_news_static_rules.py`).
Nothing in the existing Stages 1-10 code was touched.
- **`StrategySpec`** (`engine/spec.py`): `strategy_id`, `version`, `context_tfs` (coarser-or-equal to
  `setup_tf`, may be empty), `setup_tf`, `trigger_tf` (same-or-finer than `setup_tf` - a strategy is
  evaluated only on its own `trigger_tf`'s close), `warmup_bars`, `allowed_regimes` (a `frozenset` of
  `Regime.label` strings, or `None` for no gate). Validated in `__post_init__`, matching the project's
  existing dataclass-validation style (e.g. `CandidateSignal`).
- **`BarCloseEvent`** (`engine/events.py`): one timeframe's bar closing for one symbol - `open_ms`,
  `close_ms` (= the decision/event time), `available_at_ms` (`close_ms` + a configured delay, computed the
  same way as `core.timeframes.bar_available_at`, never differently).
- **`EventClock`/`SimulatedEventClock`** (`engine/clock.py`): the event-driven analogue of
  `backtest.clock.Clock`/`SimulationClock` (kept, unmodified, for the legacy path). Builds the full ordered
  event sequence once, up front, from a fixed set of timeframes over `[start_ms, end_ms)` - same
  determinism approach as the legacy clock's precomputed grid. **Documented tie rule**: events sharing the
  same `close_ms` are ordered coarsest-timeframe-first (sort key `(close_ms, -timeframe.ms)`) - a 4h close
  always coincides with a 1h/15m/5m/1m close, and this ordering guarantees any coarser-or-equal timeframe a
  strategy reads as context has already been emitted as closed by the time its own, finer `trigger_tf`
  event fires at that same instant. This removes a whole class of same-instant look-ahead bugs by
  construction (event order itself), not only by relying on `available_at` arithmetic downstream. Single-
  symbol for now (multi-symbol is master-prompt phase 9, explicitly separate).
- **Validation**: 32 new tests (`tests/engine/`) covering construction validation, the `now_ms`/`started`
  contract (mirrors `SimulationClock`'s own "clock has not started" / stays-put-after-exhaustion
  behaviour), the coarsest-first tie rule (including a 3-timeframe coincident-close case), strictly
  non-decreasing `close_ms` across the whole sequence, availability-delay arithmetic, and determinism
  (identical construction ⇒ byte-identical sequence; timeframe argument order does not affect the result).
  Full suite: **1740 passed, 13 skipped** (1708 + 32 new; no regressions anywhere in Stages 1-10).
- **Not yet built** (explicitly later phases): per-timeframe feature tables, `MultiTFView`, the live
  `EventClock` implementation, and the event-driven backtest loop itself (master-prompt phases 2-3) -
  `EventClock` right now only schedules events; nothing yet consumes them.

**Phase 2 — per-timeframe features + `MultiTFView` + leakage suite (done, 2026-10-07).** Three new files in
`src/arven/engine/` (`errors.py`, `features.py`, `multitf.py`); Phase 1's files and every Stage 1-10 file
untouched. Reuses the existing causal primitives directly - `BarSeries.regularized()` (`core/series.py`), the
`features/indicators.py` functions (`ema`, `atr`, `adx`, `log_ratio`, `safe_divide`, `shift`, `finite_or_nan`)
and `features/asof.asof_index` - but deliberately **not** Stage 3's `features/bars.py`/`builder.py`/`registry.py`
machinery (that frozen 61-column 1h-grid set feeds the golden `result_hash`; a new static test enforces that
the engine imports only `features.indicators`/`features.asof`).
- **`LookAheadError`** (`engine/errors.py`): same concept as `backtest.errors.LookAheadError`, new home -
  `arven.engine` may not import `arven.backtest` (module boundary). Deliberately *not* a subclass of the
  legacy class.
- **Per-TF feature tables** (`engine/features.py`): one generic function, `compute_tf_features(bars, params)`,
  the same code for every `Timeframe` (no per-TF builder dict like `bars.PREFIX`). Steps: `regularized()`
  (gap-free grid, missing/incomplete bars become NaN rows with `complete=False`), the shared primitives
  (seeded at the first stored bar, warm-up `max(p, ceil(warmup_factor*p))` exactly as Stage 3), non-finite →
  NaN. Result: `TFFeatureTable` (`timeframe`, `version="tf-v1"`, per-row `open_ms`/`close_ms`/`available_at_ms`
  (= `BarSeries.available_at_ms`, i.e. close + delay)/`complete`, `names`, a 2-D `values` array,
  `content_sha256()`; validated layout, strictly increasing `available_at_ms`). Indicator set, kept minimal
  and "boring" - the families the existing regime detector actually reads plus ATR for volatility-normalised
  stops: `close`, `atr_14`, `atr_pct_14` (ATR/close), `ema_dist_20`, `ema_dist_50` (log close/EMA),
  `ema_slope_50` (log EMA50 vs 5 bars earlier), `adx_14`. Parameters live in a frozen, validated
  `TFFeatureParams` dataclass whose defaults mirror `config/features.yaml` (ATR/ADX 14, EMA 20/50, warm-up
  factor 5); moving them to YAML is left to the phase that first consumes them. **Naming:** unqualified
  inside a table (`adx_14`); `qualified_name(tf, name)` = `"<tf>.<name>"` (e.g. `4h.adx_14`) wherever
  timeframes meet - Stage 3 names never contain a dot, so the two sets cannot collide (tested).
- **`MultiTFView`** (`engine/multitf.py`): built from per-TF tables (or `from_bars`), queried with
  `row_at(tf, t)`, `at(t, spec)` or `for_event(event, spec)` (the latter uses `event.available_at_ms` as
  "now" and refuses an event that is not the spec's `trigger_tf`). Each row is the **last row with
  `available_at <= t`** (backward as-of via `asof_index`), returned as a frozen `TFRow` (times, `bars_seen`,
  `complete`, `stale`, read-only `values`) inside a `MultiTFSnapshot` (`trigger`, `setup`, `context` in
  `spec.context_tfs` order). Three outcomes, kept distinct on purpose: (1) **no row at all** for a requested
  timeframe at `t` (before its first bar closed, or an empty table) → `LookAheadError`, since the only row
  that could fill the slot is a future one (the engine maps this to `NO_TRADE`); (2) **stale** - a row exists
  but `t - available_at >= tf.ms` (a newer bar should exist but the feed stopped) → the row is returned with
  `stale=True` and **all values NaN**, never carried forward (identical to the Stage 3 builder's
  `max_age_ms = tf.ms - 1`); a missing trigger bar at the end of data therefore shows up as a stale trigger
  row; (3) **fresh** row → returned as is, where individual NaNs (warm-up, gap rows, zero division) are a
  *defined* reading under the existing "NaN in, NaN out, never raise" convention, not an error.
  `StrategySpec.warmup_bars` is not enforced by the view - rows expose `bars_seen` so the Phase 3 engine can.
  Same-instant closes: a coarser bar closing exactly at `t` is visible (`<=`, not `<`), consistent with
  Phase 1's coarsest-first tie rule (tested against `SimulatedEventClock`'s own events at a 4h boundary).
- **Validation (the Phase 2 gate)**: 146 new tests in `tests/engine/`. `test_tf_features.py` (27):
  hand-computed values and exact warm-up boundaries (constant bars, an EMA/ATR/ADX ramp), equality with the
  shared primitives on synthetic data, gap/incomplete-bar NaN rows with recursive restart, timeframe
  agnosticism, delays, determinism, parameter/table validation, no name collision with Stage 3.
  `test_multitf.py` (16): raise before the first close and on an empty table, the exact as-of boundary
  (visible at `close`, not at `close - 1 ms`; with a delay only at `close + delay`), the 4h/1h/15m
  same-instant tie case, `for_event` with a delay, stale rows (all NaN), a missing trigger bar → stale
  trigger, warm-up NaN does not raise, configuration errors. `test_engine_leakage.py` (100): through the
  existing `tests/leakage_harness.py`, **truncation and perturbation tests for every new feature column on
  every timeframe** (4 TFs × 7 columns, each parametrised, plus non-vacuity checks) and **for `MultiTFView`**
  under three specs (15m/1h/4h, 1h/1h/4h, 5m/15m/(1h,4h)) covering every role/feature value and the row
  metadata (`open_ms`, `available_at_ms`, `bars_seen`, `complete`, `stale`, raised-or-not); also on gappy
  data with stale 4h rows, with a 60 s availability delay (including exact close+delay instants), and driven
  by `SimulatedEventClock` trigger events against views rebuilt from `available_until(event.available_at_ms)`;
  plus a canary - a deliberately leaky view that peeks one bar ahead **is** caught by both harness checks.
  `test_engine_phase2_static_rules.py` (3): the Phase 2 modules exist and import nothing from
  decision/risk/strategies/regime/backtest; the engine imports only `features.indicators`/`features.asof`;
  no `shift(-n)`/`bfill`/centered windows. All pass (engine suite ~18 s). Full suite: **1886 passed, 13
  skipped** (1740 + 146 new; no regressions - `tests/pipeline/test_stage5_no_ml_regression.py` green, the
  golden `result_hash` code path untouched).
- **Not yet built** (later phases): wiring `MultiTFView` into a running loop (Phase 3, event-driven backtest
  on top of Stage 4 execution, where the identical-`result_hash` gate applies), enforcing `warmup_bars`/regime
  gates, a persisted `features_<tf>` cache/DuckDB table (tables are computed in memory for now), YAML config
  for `TFFeatureParams`, and swing/pivot/zone features for strategy S4 (Phase 7).

**Phase 3 — event-driven backtest loop on top of Stage 4 execution (done, 2026-10-07).** One new source file,
`src/arven/backtest/event_engine.py`; plus a docstring correction in `src/arven/engine/__init__.py` and an
explanatory comment in `tests/engine/test_engine_static_rules.py` (rule itself unchanged). No existing logic
touched - `backtest/engine.py`, `execution.py`, `clock.py`, `provider.py`, `types.py`, `report.py` and every
Phase 1/2 file are byte-for-byte as before.
- **`EventBacktester`**: same constructor and validation as the legacy `Backtester` (`app, cfg, window,
  market, features, stress`; taker-only costs, `latency >= bar availability delay`, market window = allowed
  window, feature rows = the window's hourly grid). `run(clock: EventClock, providers: Mapping[Timeframe,
  SignalProvider]) -> BacktestResult` (the legacy dataclass itself, so `report.result_hash`, metrics and run
  artifacts consume it unchanged). For every event the clock emits whose timeframe has a registered provider
  it makes **exactly the legacy call sequence** on the unchanged Stage 4 `Simulator`: `j =
  first_at_or_after(close_ms)`, `run_window(cursor, j)`, `add_point(close_ms, close[j-1], DECISION)`, a
  `PortfolioSnapshot`/`DecisionContext` (legacy `FeatureView` bound to the event's `close_ms`; `ctx.index` is
  the provider's own decision count), `decide()` only on the provider registered under `event.timeframe`,
  and the identical signal → order / reject handling (`position_open`, `exceeds_leverage_cap`, close /
  `close_ignored`, wrong signal time → `SignalError`). `prepare()` is called once per provider before the loop
  (coarsest timeframe first) with that timeframe's own decision grid; one final `run_window(cursor, len(md))`
  + `finish()` at the end. Decision time = bar close, the same convention as the legacy grid; availability
  delay is handled exactly as before, through `latency_ms`.
- **Multi-timeframe semantics**: events of timeframes with no registered provider are skipped *entirely* (no
  simulator call - the next dispatched event's `run_window` covers those minutes), so adding unused
  timeframes to the clock cannot change a result (tested). Same-instant events follow the clock's own
  Phase 1 coarsest-first order. One account, one net position: an entry from a second provider while an
  order is pending or a position is open is rejected `position_open`, as a repeated legacy entry is - no
  pyramiding. Strict clock validation, all → `DataError`: an event before the previous one, an event outside
  `[window.start, window.end)` (even for an unregistered timeframe), a registered timeframe's event that is
  not the next expected decision time, or a clock that ends before emitting every decision time of a
  registered timeframe. In particular a `SimulatedEventClock(start, end)` built naively over the window is
  refused rather than silently producing an hour-shifted backtest: its closes are `start+1h .. end`, while the
  window's decisions are `start .. end-1h` (the legacy grid's first decision is the close at `start` of the bar
  that opened before the window). `WindowEventClock(symbol, timeframes, start, end, delay)` (same file)
  builds the correct clock for any timeframe set: a `SimulatedEventClock` started one coarsest bar early,
  filtered to closes in the window (Phase 1 ordering/tie rule unchanged); `timeframe_grid(start, end, tf)` is
  the epoch-aligned close grid (equals the legacy `decision_grid` for 1h - tested).
- **Module-boundary resolution**: the master prompt requires reusing Stage 4 execution unchanged, while
  Phases 1-2 established that `arven.engine` never imports `arven.backtest`. Rather than loosening that rule,
  the loop lives in `arven.backtest` and imports *from* `arven.engine` (clock and events only) - the
  dependency points `backtest -> engine`, never the reverse, so the Phase 1/2 static rules hold verbatim and
  the loop can import `BacktestResult` directly (a copy of that dataclass would have been a second definition
  of the result contract). `tests/backtest/test_event_engine_static_rules.py` (6 tests) pins the precise rule:
  the loop imports from `arven.engine` only `clock`/`events`; from `arven.backtest.engine` only
  `BacktestResult` (never `Backtester`/`decision_grid`), never `arven.backtest.clock`, never
  decision/risk/strategies/regime/ML; no legacy `arven.backtest` module imports `arven.engine` or the loop; no
  later-stage/lower-layer package (nor `arven.engine`) imports the loop. The loop also passes the existing
  package-wide `tests/backtest/test_backtest_static_rules.py` checks (no wall-clock, I/O, unseeded randomness).
  The `engine/__init__.py` docstring was corrected while there: the golden `result_hash 3eca0a70...` lives only
  in the real local artifacts under `data/` and in this document, not in the test suite; what the suite
  enforces is equality of `result_hash` between runs on identical synthetic fixtures.
- **The Phase 3 gate - identical `result_hash`** (`tests/engine/test_event_backtest_equivalence.py`, 19
  tests): the real `Stage5Pipeline` on the same synthetic features/1m market/window (the
  `test_stage5_no_ml_regression.py` fixture pattern, 180 days, market seed = seed + 1000) run through the
  legacy `Backtester.run` and through `EventBacktester.run` with a plain Phase 1 `SimulatedEventClock`
  carrying only `Timeframe.H1` (closes `start .. end-1h`) and the pipeline under `H1`. Asserted equal table by
  table (`result_tables`: meta, orders, fills, funding, trades, equity) and by `result_hash`: seeds 0, 5, 9,
  17, 22 with real costs and with zero costs, seeds 0 and 22 under 2x cost stress, seeds 0/9 via
  `WindowEventClock`, seeds 0/17 with a clock that also carries 15m and 4h events (no provider on them), an
  all-`None` 150-day run, and a hand-made market with a scripted provider that hits every order branch
  (entry, `position_open` and leverage-cap rejections, `NO_TRADE`, close, `close_ignored`; exits STOP,
  SIGNAL_CLOSE, TIME_STOP, TAKE_PROFIT; funding while in a position). Every pipeline seed has real trades
  (11-65 per run; asserted, plus positive fees in the real-cost runs), and the seed set as a whole includes
  funding settlements and END_OF_PERIOD closes (asserted). **All hashes matched exactly; no tolerance.**
- **Multi-timeframe dispatch + orchestration** (`tests/engine/test_event_backtest_loop.py`, 23 tests):
  counting providers on 1h and 15m are each called exactly once per own-timeframe close and never on the
  other's (6 and 24 calls over 6 h, `ctx.index` per provider); with 4h/1h/15m providers the order at 4h
  boundaries is 4h, 1h, 15m and at other hours 1h, 15m; `prepare` once per provider, coarsest first, before
  any decision, with its own grid; unregistered timeframes skipped; two same-instant entries open one
  position (second rejected `position_open`); a 15m provider sees the 1h provider's pending order and then the
  filled position; the `FeatureView` refuses rows after the event time (`LookAheadError`, also for a 15m
  provider reading the 1h row that has not closed yet); wrong-time signal; every clock-validation error
  above; empty providers / one provider under two timeframes → `ConfigurationError`; constructor rejects the
  same inputs as `Backtester`; `WindowEventClock` contents/ordering/validation.
- **Counts**: 48 new tests (19 + 23 + 6) plus 2 automatic ones (the package-wide backtest static rules
  parametrise over every `backtest/*.py`, now including `event_engine.py`). Full suite: **1936 passed, 13
  skipped** (1886 + 50; no regressions; `tests/pipeline/test_stage5_no_ml_regression.py` green with its
  assertions untouched).
- **Not yet built / deliberately left for later phases**: wiring `EventBacktester` into `arven.runs`/the CLI,
  `arven.paper` or a live loop (the legacy `Backtester` still drives all of those); the live `EventClock`
  (Phase 5); migrating any strategy from the legacy `FeatureView` to `MultiTFView`, enforcing
  `StrategySpec.warmup_bars`/regime gates in the loop, per-strategy risk budgets and the global net-exposure
  cap (with one provider per timeframe today, "one net position" is enforced by the shared `Simulator`); Signal
  object v2, paper tracker in R, signal store and grading gate (Phase 4); `docs/architecture.md` has not yet
  been updated for the build-out (the master prompt's definition of done schedules that).

**Phase 4 — signal object v2, R/TP-ladder paper tracker, signal store, grading gate (done, 2026-10-08).**
Six new files, five in `arven.engine` (pure types, no dependency on `arven.backtest`) and one new module in
`arven.backtest` (reuses the Stage 4 fee/slippage model, same `backtest -> engine` dependency direction
Phase 3 established - `tests/backtest/test_paper_tracker_static_rules.py`). Nothing in Stages 1-10 or
Phases 1-3 was modified except one existing Phase-3 test, corrected below.
- **`EngineSignal`** (`engine/signal.py`, section 5.3): `signal_id` (sha256 of the signal's own canonical
  content, computed in `__post_init__`, never supplied), `symbol`/`side`/`strategy_id`+`version`/`grade`/
  `event_time_ms`/`entry_reference`/`stop`/`tp_ladder`/`risk_fraction`/`confidence`/`regime`/`reasons`/
  `risk_checks`/`versions`/`max_holding_minutes`. **Additive, not a replacement**: `core.signal.Signal` (the
  legacy decision-engine output `Backtester`/`EventBacktester` consume) is untouched - `EngineSignal` is a
  separate, richer object built *from* a decision, for display/forward-tracking, never fed back into Stage
  4 execution. `TPLevel.from_r_multiple(r, fraction, entry=, stop=, side=)` derives each rung's price from a
  planned R-multiple (never supplied independently, so price and `r_multiple` can never disagree); a ladder
  is validated nearest-rung-first, fractions summing to at most 1.0 (less than 1.0 is allowed - the
  remainder may run with a trailing/no stop). `r_plan` is a property reading the ladder's own `r_multiple`s
  (not a second stored copy - one source of truth). `SignalUpdate`/`SignalUpdateKind` (`engine/signal_events.py`):
  append-only (`TP_HIT`/`STOP_MOVED`/`CLOSED`/`CANCELLED`) - the signal itself never changes after
  construction; its history is this event sequence instead.
- **The grading gate** (`engine/grading.py`, section 1.3): `Grade.EXPERIMENTAL`/`VALIDATED`/`SUSPENDED`
  computed by a pure function of a caller-assembled `TrackRecord` - majority-positive walk-forward windows,
  >=100 simulated trades, beats all three baselines, survives cost stress, >=30 forward trades with
  non-negative net expectancy (all six, not a majority) for `VALIDATED`; a rolling-30-trade expectancy below
  -0.3R or a drawdown above 8R forces `SUSPENDED` **even over an otherwise-qualifying record** (CLAUDE.md
  rule 6: the owner must never be able to mistake a degraded strategy for a currently-trustworthy one).
  Deliberately does not read any real Stage 7/8 artifact itself - wiring a real strategy's real history into
  a `TrackRecord` is later-phase integration work.
- **`resolve_legs`** (`engine/ladder.py`): the hard, hand-computed Phase 4 gate. Pure summation over already-
  resolved `ClosedLeg`s (fraction, actual fill price, fee, reason) - mirrors
  `arven.backtest.accounting`'s existing single-exit convention exactly (`risk = |entry - stop|`,
  `r_multiple = net_pnl / risk`, generalised to many legs: a ladder that fills every rung exactly at its
  planned price blends to `sum(fraction_i * r_multiple_i)` before fees - verified by hand for a 3-rung
  ladder, a partial-then-breakeven-stop case, a short, and a fees-reduce-R case).
- **`track_signal`** (`backtest/paper_tracker.py`): walks 1m bars forward from an already-resolved entry
  fill (the real fill - with its own latency/slippage - is given, not recomputed here) to produce the
  `ClosedLeg` sequence `resolve_legs` needs. Reuses `backtest.costs` (`taker_fee_rate`/`slippage_fraction`/
  `adverse_price`) directly for every leg's fill. **Intrabar rules** (hand-tested): a stop always beats a
  take-profit in the same bar (mirrors `execution.py`'s documented rule exactly); **at most one rung (or the
  stop) resolves per bar**, even if a single bar's range technically reaches two rungs at once - a
  deliberate, conservative choice (never assume an intra-minute order the 1m data cannot distinguish,
  the same spirit as CLAUDE.md's "assume the worse outcome", applied here as "assume the slower outcome").
  An optional `move_stop_to_breakeven_after_first_tp` flag moves the stop to the entry fill price once the
  first rung fills (emitting a `STOP_MOVED` update); risk for the final R-multiple always uses the
  *original* stop, never the moved one (R measures against the original plan). `max_holding_minutes`, if
  set, closes the remainder at the deadline bar's open (`TIME_STOP`). Returns `resolution=None` (not an
  error) when the given market data runs out before anything ever triggers - a legitimate "still open"
  outcome, not a misconfiguration.
  - **Deliberate scope cut, documented not hidden**: funding is not modelled here (CLAUDE.md rule 4 asks
    every *backtest* to model it; this is a forward tracker for one signal's own typically-hours-long life,
    and Phase 4's gate is specifically the R/TP-ladder math - fees and slippage are the costs that scale
    with every leg and had to be proven correct first). Left for later if a real signal's holding time makes
    it material.
- **`signal_store`** (`engine/signal_store.py`): the same append-only JSONL-index idiom already used
  throughout this project (`arven.paper.runs`'s `runs.jsonl`/`decisions.jsonl`, not a new DuckDB schema) -
  `<root>/<strategy_id>/signals.jsonl` and `.../updates.jsonl`. `read_signals` recomputes and checks every
  stored `signal_id` against its own content on the way back out, refusing a tampered/corrupted row rather
  than silently trusting it.
- **A pre-existing Phase 3 test was corrected, not weakened**: `test_event_engine_static_rules.py`'s
  "legacy backtest modules never import the engine" check had only ever excluded `event_engine.py` by name;
  Phase 4 added a second, equally legitimate new module (`paper_tracker.py`) that also needs to import from
  `arven.engine`, so the check now excludes both new modules by name while still forbidding every *other*
  `arven.backtest` file (`execution.py`, `clock.py`, ...) from importing either.
- **Counts**: 78 new tests (16 `test_ladder.py` + 10 `test_paper_tracker.py` + 16 `test_signal.py` + 3
  `test_signal_events.py` + 7 `test_signal_store.py` + 14 `test_grading.py` + 7 `test_paper_tracker_static_rules.py`,
  plus the pre-existing engine static-rules tests already covering the new `engine/*.py` files with no change
  needed). Full suite: **2014 passed, 13 skipped** (1936 + 78; no regressions; golden regression green).
- **Not yet built / deliberately left for later phases**: wiring any of this into a real running strategy,
  `arven.paper`, Telegram or the web app (Phase 5 is the always-on runtime; Phase 6 is Telegram; Phase 8 is
  the web app); a real `TrackRecord` assembled from actual Stage 7/8 artifacts; funding in the paper tracker
  (see above); enforcing a maximum number of open signals per strategy or the global net-exposure cap across
  *tracked* (not just backtested) positions.

**Phase 5 — always-on paper runtime, `LiveEventClock` (code done and unit-tested 2026-10-08; the phase's
own 48h-soak gate deliberately not yet run - see "Known limitation" below).** Two new pieces: `LiveEventClock`
(`engine/clock.py`, additive to Phase 1's `SimulatedEventClock`) and the polling loop itself
(`arven.paper.runtime`, new package-internal module; `arven paper runtime`/`heartbeat` CLI commands).
Nothing in Stages 1-10 or Phases 1-4 was modified.
- **No new decision/execution logic.** Every tick calls the existing, already-idempotent,
  already-catch-up-capable `arven.paper.runs.run_paper_tick` unchanged - REST-tail, resampling, the real
  `Stage5Pipeline`/`Backtester`, and Stage 8's own staged-bulk-load DuckDB fix are all reused exactly as
  built, not re-derived (section 5.2 asks to "avoid the known DuckDB trap" again - it was already avoided
  in Stage 8's `data/rest_ingestion.py`).
- **The one genuinely new piece of logic, and why it is necessary, not just an optimisation**:
  `run_paper_tick` has no "nothing changed" short-circuit of its own - every call that reaches
  `execute_run` writes a brand-new run artifact under `data/paper/`, even if the forward decision grid has
  not advanced since the last call. Polling every 10-20s without a guard would therefore flood that
  directory with hundreds of fully-duplicate artifacts per hour. `paper.runtime.run_once` adds exactly one
  cheap, pure, no-I/O check (`latest_forward_window_end_ms` unchanged since the last tick => skip, report
  `"idle"`) before doing any REST/DuckDB work - confirmed by a dedicated test that a second poll at the same
  wall-clock time produces no new artifact, and a later poll (an hour on) does.
- **"Persist the last processed event, restart-safe" is already true of `run_paper_tick` itself** (it
  always replays `[forward_start, now)` fresh from the database, the source of truth), so no second,
  redundant cursor file was added. What *is* new, purely for external monitoring: an atomically-written
  (write-temp-then-rename) `data/paper/heartbeat.json` (`status`/`checked_at_ms`/`last_tick_ms`/`detail`)
  and an append-only structured tick log, `data/paper/runtime.jsonl`. `is_stale(heartbeat, now, max_age)`
  is the runtime's own analogue of CLAUDE.md rule 5 ("missing/stale data => NO_TRADE"), applied to
  monitoring the *process* rather than any one data source; `arven paper heartbeat` exits non-zero when
  stale or when the last status was `"error"`, for a Task Scheduler health-check trigger.
- **One bad tick never kills the loop**: `run_once` never raises - a transient REST failure or any other
  exception becomes `status="error"` with the exception recorded in `detail`, logged, and polling continues
  on the next interval (hand-tested with an opener that always raises `OSError`).
- **`LiveEventClock`** (`engine/clock.py`): the live counterpart of Phase 1's `SimulatedEventClock` (section
  5.1's "a live implementation (bar confirmed closed + derived TF bars complete)"), built now for
  architectural symmetry but **not yet consumed by the real paper loop** (which still uses its own
  `latest_forward_window_end_ms`/1h-only detection, pre-dating Phase 1) - wiring it in is deferred until a
  genuine multi-timeframe strategy exists to need it (Phase 7), the same "don't build it until something
  needs it" discipline as `MultiTFView`'s own still-unused status. Restart-safe by construction rather than
  a persisted cursor: the constructor takes `start_after_ms` (wherever the caller already durably recorded
  its own progress) and every timeframe resumes independently from the boundary at-or-before that instant;
  one `advance()` call drains every bar a timeframe missed while the process was down, oldest first, before
  moving to the next timeframe (hand-tested: a wall-clock jump of 3 hours after being "down" emits all 3
  missed 1h closes in order). One wall-clock read per `advance()` call, via an injectable `now_fn` (mirrors
  `run_paper_tick`'s own injectable `now`), so tests fully control what time it believes it is.
- **Graceful shutdown is cooperative, not signal-based**: Windows' asyncio event loop does not support
  POSIX signal handlers, so `arven paper runtime` relies on a plain `KeyboardInterrupt` handler (Ctrl+C) and
  an optional, portable `--stop-file` sentinel (checked once a second) instead - both documented in the new
  `docs/RUNTIME_OPERATIONS.md`, which also carries the Windows Task Scheduler "restart on failure" recipe
  and power-settings note section 5.2 asks for (a laptop set to sleep when plugged in, or with "closing the
  lid" set to sleep, is not 24/7 regardless of what Task Scheduler does).
- **Counts**: 23 new tests (9 `test_live_clock.py` + 14 `test_runtime.py`, offline throughout - fake REST
  opener, injectable clocks, no real sleep: `run_forever`'s own tests run in well under a second using
  `poll_seconds=0`/`asyncio.Event`). One pre-existing Phase 2 static-rules test
  (`test_engine_has_no_lookahead_prone_idioms`, a regex scan for leakage-prone idioms across `engine/*.py`)
  false-positived on the prose word "backfill" in a new `LiveEventClock` docstring describing real-time
  catch-up (not a leakage pattern at all); fixed by rewording the docstring, not by touching the still-valid
  check. Full suite: **2037 passed, 13 skipped** (2014 + 23; no regressions; golden regression green).
- **Known limitation - not run, not hidden**: Phase 5's own gate in `docs/ARVEN_MASTER_PROMPT.md` is *"48 h
  soak on live public data: no duplicate/skipped events, correct stale => NO_TRADE"*. That is a real-time,
  multi-day observation against the real Binance API and a laptop that must stay powered/awake for two
  days - not something any single interactive session can complete synchronously, and not started
  unilaterally (launching an unattended, multi-day, always-on network process is exactly the kind of
  resource commitment this project's own working agreement asks to confirm with the owner first). Everything
  above was validated offline, against fakes, exactly like every other phase's unit tests - the soak itself
  is a deliberate, acknowledged next step, not a silently-skipped requirement. `docs/RUNTIME_OPERATIONS.md`
  has the recipe ready for whenever the owner chooses to start it.
- **Not yet built / deliberately left for later phases**: wiring `LiveEventClock` into the actual paper
  loop (deferred until a multi-timeframe strategy exists, Phase 7); Telegram alerts on top of the heartbeat/
  log (Phase 6); any web visibility into runtime health beyond the CLI (Phase 8).

**Phase 6 — Telegram alerts, bot commands, outbox (code done and unit-tested 2026-10-08; the phase's own
"owner supplies token for a live test" step not yet done).** New package `src/arven/telegram/` (`client.py`,
`outbox.py`, `messages.py`, `commands.py`, `runs.py`), `src/arven/core/telegram_config.py`,
`config/telegram.yaml`, two new DuckDB tables (`telegram_outbox`, `telegram_chat_state`,
`SCHEMA_VERSION` 2 -> 3). CLI: `arven telegram send`/`commands`/`test`. Nothing in Stages 1-10 or Phases
1-5 was modified except the schema file (purely additive DDL, no existing table touched).
- **Stdlib HTTP only, no SDK** (`telegram/client.py`): the same choice already made twice (Binance REST,
  the Anthropic API). `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_IDS` are both secrets, read from the environment/
  `.env` only (never a YAML file) - `TELEGRAM_CHAT_IDS` fails closed (an empty allow-list, not "allow
  everyone") when unset, unlike a token which raises outright. **429 rate-limiting is honoured exactly**:
  a 429 response's own `retry_after` is read and slept for verbatim before the retry (hand-tested:
  `sleep` is called with exactly the server-supplied value, not a generic backoff).
- **The persisted outbox** (`telegram_outbox`): "idempotent sends (dedupe by signal_id + event type)"
  (section 5.4) is the primary key itself - `outbox_id = sha256(signal_id, event_type, chat_id)` - so
  enqueuing the same alert twice is a no-op, verified by test. An entry that keeps failing becomes
  permanently `"failed"` after `max_send_attempts` (config), never retried forever and never silently
  dropped - still visible in the table either way. `/pause`/`/resume` only toggle a **per-chat** mute flag
  in a second new table (`telegram_chat_state`) - this never touches the trading loop or any other
  strategy's chat, by construction (there is nothing in this package that *could* reach decision/risk/
  strategy code - enforced by a static test, same pattern as `arven.news`/`arven.llm`).
- **Message text is pure formatting of already-computed data** (`messages.py`, CLAUDE.md rule 9): the four
  kinds from section 5.4 (new signal with its full TP ladder, a signal update, a system alert, a daily
  summary), every one carrying the simulated/not-financial-advice disclaimer (hand-verified: every field of
  a hand-built `EngineSignal` - entry, stop, every TP level's price/R/fraction, risk %, confidence, regime,
  up to 3 reasons - appears correctly in the formatted text).
- **Bot commands** (`/start /status /signals /history /strategies /pause /resume /help`, `commands.py`):
  read-only over already-stored data - `/status` reads the real `paper.runtime` heartbeat (genuinely wired
  to Phase 5's own file, not a stub); `/signals`/`/history`/`/strategies` read the real Phase 4
  `engine.signal_store` (genuinely wired, though nothing yet *writes* a real signal there in production -
  see "Not yet built" below). An unrecognised command (or any non-command text) gets no reply at all - this
  is an alerts bot, not a general chat assistant.
- **A real bug found while smoke-testing the CLI commands by hand** (not by the unit tests, which all
  passed first try): `arven telegram commands` crashed with a raw traceback when `TELEGRAM_BOT_TOKEN` was
  unset, because `run_telegram_commands_tick`'s own `get_updates` call - unlike every entry in
  `run_telegram_send_tick`'s own loop, which already catches per-entry - was not wrapped in a
  try/except. `arven telegram send` happened not to crash only because its default `dry_run: true` short-
  circuits before ever needing a token. Fixed at the source (`telegram/runs.py`): a `getUpdates` failure
  (missing token, or a real network failure) is now recorded in the tick's own `errors` list, the same
  never-raise discipline `run_news_tick`/`paper.runtime.run_once` already follow for their own primary
  call - with a regression test.
- **A second, self-inflicted test false positive, fixed immediately**: the static "no order/account
  endpoint" check for `telegram/client.py` originally also forbade the substring `"binance"` (copied
  without thinking from an unrelated check) and tripped on the client's own docstring, which legitimately
  *mentions* `binance_rest` as a stylistic precedent. Fixed by dropping that irrelevant word from the
  check, not by rewording accurate prose.
- **Counts**: 56 new tests across `tests/telegram/` (client retry/429/auth, outbox dedupe/failure-cap,
  message formatting, command handling incl. the real heartbeat/signal-store wiring, the two composition
  roots end-to-end against a scripted fake HTTP server, plus the `getUpdates`-failure regression above) and
  static module-boundary rules. Full suite: **2093 passed, 13 skipped** (2037 + 56; no regressions; golden
  regression green).
- **Known limitation - not run, not hidden**: the master prompt's own Phase 6 gate is *"fake-server tests;
  owner supplies token for a live test"*. The first half is done (56 tests, all against a scripted fake
  Bot API - never a real socket). The second half - a real `TELEGRAM_BOT_TOKEN` and at least one real
  `TELEGRAM_CHAT_IDS` entry, then `arven telegram test` to confirm an actual message arrives - has not
  happened in any session; this is the same category of acknowledged gap as Stage 9b's own
  never-called-the-real-Anthropic-API status, not a new kind of shortcut.
- **Not yet built / deliberately left for later phases**: nothing in production actually *writes* a real
  `EngineSignal` yet (no strategy emits one live - that starts at Phase 7), so `/signals`/`/history`/
  `/strategies` and the "new signal"/"position update"/"daily summary" message types are real, tested code
  with nothing real yet to show; wiring system alerts (data stale, process restarted) from
  `paper.runtime`'s own heartbeat into the outbox automatically (today the outbox only has what
  `arven telegram send` is handed - nothing enqueues anything yet); editing a sent message via
  `edit_message_text` when a position updates (the client function exists and is tested, nothing calls it
  yet); a `--daemon` mode for `arven telegram send`/`commands` analogous to `arven paper runtime` (both are
  one-shot CLI ticks today, meant to be scheduled the same way Stage 8's `arven paper run` originally was).

**Phase 7a — strategy S4 "Impulse-Retest": spec + causal detection math (done, 2026-10-08; 7b - wiring +
evaluation - is next, not yet started).** `docs/strategy_impulse_retest.md` (written *before* any code, per
the master prompt's own explicit requirement) and one new file, `src/arven/engine/strategy_s4.py` - pure
computation, no `arven.backtest` dependency (the engine module-boundary rule holds for this file too; a
`SignalProvider` adapter that *would* need `arven.backtest` is explicitly deferred to 7b, mirroring the
Phase 3/4 `backtest -> engine` pattern). Nothing in Stages 1-10 or Phases 1-6 was touched.
- **Every parameter is pre-registered in the spec, not fitted**: swing confirmation lag `K=2` (2-bar
  fractals), impulse size `>= 3x ATR(14)`, base-candle `>= 1x ATR(14)`, stop buffer `0.25x ATR(14)`, Fibonacci
  retracement band `0.5-0.618` (given verbatim by the master prompt), extension targets `1.0/1.414/1.618`
  with close fractions `50%/30%/20%`. The spec's own §11 is an append-only log of every variant ever tried
  (multiple-testing disclosure) - it currently has exactly one row, this first version, nothing evaluated
  yet.
- **What `context_tfs=(4h,)` concretely means was underspecified by the master prompt text itself**
  (it only says "context", not a rule) - made concrete and documented in spec §1.1: a setup is only taken
  when its direction agrees with the 4h `ema_slope_50` sign, reusing Phase 2's own already-computed
  per-timeframe feature (`engine.features`) via a single `MultiTFView` row lookup, rather than inventing a
  second trend computation. This is the *only* place this strategy touches `MultiTFView` - swing/impulse/
  zone/trendline/trigger (spec §§2-7) operate on raw, causally-truncated `BarSeries` history instead
  (`BarSeries.available_until(t)` already gives exactly "what was known at t" - truncate first, then
  compute, the same idiom Stage 3's own feature code relies on - `MultiTFView` is for a single as-of
  *row*, not the full history a swing/impulse search needs).
- **Deliberate methodology choice, documented not hidden** (spec §10): the backtest/WFO/baselines/stress
  evaluation (7b) will use S4's nearest target (TP1) and its stop only, through the unchanged Stage 4
  execution model - exactly like every other strategy's existing single-exit backtest. The full multi-rung
  ladder (TP1/TP2/TP3) is evaluated on the forward/paper leg instead, via the Phase 4 `paper_tracker` that
  already resolves a ladder one rung at a time in order (which is also exactly the "TP2 unlocks only after
  TP1" rule - not separate logic, a consequence of how the tracker already works). No change to Stage 4's
  execution layer was made or is planned for this.
- **A real sign-error bug found by the hand-computed tests themselves, before anything else used this
  code**: `build_decision`'s first draft computed `r_multiple = side * (fib * size) / risk`, which gives a
  *negative* R for a short's profit target (since `side * (price - entry) = side * (side * fib * size) =
  fib * size` always - `side` cancels via `side**2 == 1`, so multiplying by it once is wrong both ways).
  Fixed to `r_multiple = (fib * size) / risk` (no `side` factor at all); the long case was unaffected
  (`side=1` made the bug invisible there), which is exactly why the explicit short-side hand-computed test
  mattered.
- **Counts**: 27 new tests (`tests/engine/test_strategy_s4.py`): `confirmed_swings` (clean swings, strict-
  inequality/plateau rejection, `k` validation, NaN-adjacency, and a dedicated **truncation/leakage test**
  per CLAUDE.md's "mandatory for every feature" rule - a swing confirmed within a truncated prefix must
  exactly match the same swing computed on the full array); `find_last_impulse` (qualifying/too-small,
  not-yet-confirmed, skipping a same-kind-adjacent pair to find an older qualifying leg, both directions,
  no-swings); `confluence_zone` (full/partial overlap fraction, too-small base candle, non-overlapping
  bands, start-at-index-0); `counter_trend_trendline` (last-two-pivots, not-yet-confirmed, ignores pivots
  before the impulse); `find_trigger` (break-then-hold, never-breaks, short side, never-triggers-in-range);
  `build_decision` (stop/target prices and R-multiples by hand for both sides, confidence clamping). Full
  suite: **2120 passed, 13 skipped** (2093 + 27; no regressions; golden regression green).
- **Not yet built (7b, explicitly next)**: a `SignalProvider` adapter (`arven.backtest.strategy_s4_provider`,
  mirroring the Phase 3/4 `backtest -> engine` dependency direction) converting an `ImpulseRetestDecision`
  into both a legacy `core.signal.Signal` (for the backtest, §10) and a full `EngineSignal` (for paper/
  live, with the complete ladder); the development backtest itself (via `EventBacktester`, S4 registered
  under `Timeframe.M15`); the windowed robustness check, baselines, cost stress, the S4-specific per-
  regime-like breakdown (spec §9 - cannot reuse `arven.regime`, the engine boundary rule holds); wiring a
  real forward/paper run; a `TrackRecord` and the grade the gate (`engine.grading`) would assign from any
  of the above.

**Phase 7b, part 1 — the S4 `SignalProvider` adapter, wired and hand-verified end to end (done, 2026-10-08;
part 2 - the actual development backtest/WFO/baselines/stress/per-regime/forward-paper run - is next).**
One new file, `src/arven/backtest/strategy_s4_provider.py` (`ImpulseRetestProvider`, `make_spec`), plus a
small, additive extension to the already-committed `engine/strategy_s4.py` (`setup_tf_atr` - see the
real bug below) and its own spec doc (§4's confluence-zone definition - also see below). Nothing in Stages
1-10 was touched.
- **Ignores `ctx.features` entirely.** `EventBacktester` hands every registered provider the same legacy
  1h-gridded `FeatureView` regardless of `trigger_tf` - useless for a 15m-triggered strategy. `decide()`
  instead truncates its own pre-built `setup_tf`/`trigger_tf` `BarSeries` at `ctx.now_ms` via
  `.available_until` (the same "truncate first, then compute" idiom `strategy_s4.py` already documents)
  and looks up the 4h context row from its own `MultiTFView` - never the view it was handed.
  **"Only fire on a fresh trigger"**: `find_trigger`'s result is only accepted when it lands on the
  *current* (latest-available) `trigger_tf` bar - otherwise a pattern that triggered several bars ago while
  flat would keep re-firing on every subsequent poll.
- **One decision, two renderings** (spec §10): `decide()` returns the legacy single-exit `Signal` (TP1 and
  the stop only, sized by `risk_fraction / stop_pct` - the standard risk-based position-sizing formula) for
  the backtest/WFO/baselines/stress evaluation; `to_engine_signal()` builds the full ladder `EngineSignal`
  from the *same* cached `ImpulseRetestDecision` for paper/live, so the technical-analysis math is never
  computed twice from two different code paths.
- **Two real bugs found before any backtest/evaluation ran - by actually constructing and running a
  synthetic end-to-end scenario, not only by the Phase 7a unit tests**:
  1. **A genuine cross-timeframe bug in the already-committed Phase 7a code**: `TrendLine`/`find_trigger`
     used raw bar *indices* as if they were time - correct only by accident when every test stayed within
     one timeframe's own array. Wiring S4's `setup_tf`-built trendline against `trigger_tf` bars exposed
     this immediately (a 1h index 10 and a 15m index 10 are ten hours apart vs. 150 minutes). Fixed:
     `TrendLine`/`counter_trend_trendline`/`find_trigger` now carry and compare real epoch-ms times, with a
     dedicated regression test proving the old index-based approach would have evaluated the trendline at
     the wrong real time.
  2. **A real methodology flaw in the spec itself**: §4's original "base candle = `start_swing_index - 1`"
     definition was found, empirically, to almost never overlap the Fibonacci 0.5-0.618 retracement band -
     that band sits 38-50% of the way *up* the impulse from its origin, nowhere near the single candle
     immediately before the move started. A hand-built scenario produced `zone = None` on every attempt
     with the original rule. Corrected (spec §4's own "Revision" note, §11's variant log) to search for a
     qualifying base candle *within the impulse leg itself*, nearest the end first - matching how a real
     impulsive move often pauses briefly partway through, and that pause (not the leg's starting candle) is
     what price later retests. Existing Phase 7a tests for `confluence_zone` were updated for the new
     search, not discarded.
- **A pre-existing, Stage-4-era static rule was also found and respected, not weakened**:
  `test_backtest_static_rules.py`'s package-wide "`arven.backtest` never imports `arven.features`" check
  (a CLAUDE.md rule 7 guard older than this whole build-out) caught the provider's own ATR computation.
  Fixed by moving ATR computation into `engine.strategy_s4.setup_tf_atr` (`arven.engine` may import
  `arven.features`, the same precedent Phase 2's `engine/features.py` already set) rather than loosening
  the backtest package's own long-standing boundary.
- **A third extension of the Phase 3/4 `backtest -> engine` static-rule pattern**: the same
  `test_event_engine_static_rules.py` check amended once for `paper_tracker.py` (Phase 4) now also
  excludes `strategy_s4_provider.py` by name, for the same reason.
- **Counts**: 9 new tests (`tests/backtest/test_strategy_s4_provider.py`: wrong-timeframe construction,
  insufficient warmup, a full hand-built firing scenario checking `decide()`/`to_engine_signal()` agree
  with each other, no-reentry-while-open/order-pending, the 4h context filter blocking an otherwise-valid
  setup, `to_engine_signal()` returning `None` with no cached decision) plus 5 static-boundary tests
  (`test_strategy_s4_provider_static_rules.py`) plus 2 new/updated tests in `test_strategy_s4.py` for the
  cross-timeframe fix and the confluence-zone correction. Full suite: **2139 passed, 13 skipped** (2120 +
  19; no regressions; golden regression green).
- **Not yet built (part 2, explicitly next)**: actually running S4 through `EventBacktester` on the
  development period; the windowed robustness check, baselines, cost stress; the S4-specific per-regime-
  like breakdown; wiring a real forward/paper run; assembling a `TrackRecord` and the grade
  `engine.grading` would assign from whatever those produce.

**Phase 7b, part 2 — S4 evaluated on the real development period (done, 2026-10-09): result is NEGATIVE.**
S4 v1.1 (spec `docs/strategy_impulse_retest.md`, parameters unchanged, nothing tuned) run alone through
`EventBacktester` (`Timeframe.M15` events; no other strategy, regime, ML or risk layer involved) on the
development window 2020-01-01 -> 2023-07-01 (30 648 h, 122 592 fifteen-minute decisions), repo costs config.

- **Performance bug found by running it for real, and fixed**: the first attempt did not finish in 180 s.
  Cause: `_compute_decision` recomputed Wilder ATR and `confirmed_swings` (both O(n) Python loops) from
  scratch on a growing array at every 15-minute tick (~122 000 calls) = O(n^2) wall-clock. Fixes: (1)
  `confirmed_swings` vectorised (shifted-mask comparisons + two-pointer merge keeping the exact original
  HIGH-before-LOW tie-break; existing truncation/leakage test still passes); (2) the setup-timeframe side
  (ATR, swings, impulse, zone, trendline) is cached keyed by the truncated 1h array's length, so it is
  recomputed once per hour, not per tick. New test `test_hourly_setup_cache_never_changes_a_decision`
  (cached provider == fresh provider at 11 consecutive 15m marks). One run still takes ~20 min CPU.
- **Result (base costs)**: 127 entry signals, **108 trades** (55 long / 53 short), **win rate 14.8 %**,
  total return **-20.5 %** (10 000 -> 7 948), max drawdown **38.3 %**, Sharpe -0.37.
  Gross PnL before costs +878 USDT; fees 1 471 + slippage 1 288 = 2 758 USDT -> net -2 052 USDT.
  16 take-profits (mean +5.84 R) vs 92 stops (mean -1.23 R): breakeven win rate is ~17-18 %, actual 14.8 %.
- **Cost stress (2x slippage)**: 109 trades, win rate 14.7 %, return **-27.3 %**, max drawdown 40.9 %, Sharpe -0.54.
- **Per-side / per-exit breakdown (S4's regime == impulse direction == side)**: LONG stop 44 (-5 477),
  LONG TP 11 (+5 899); SHORT stop 48 (-5 611), SHORT TP 5 (+3 136). Both sides lose; shorts hit take-profit
  less often (5 of 53 vs 11 of 55).
- **Hand audit of the trade list** (first 8 trades + aggregate checks): no stop exit is in profit, no
  take-profit exit is at a loss, entry time == decision time (fill at the next bar open per the engine's
  convention), side/stop/target geometry consistent. One trade (#2) was stopped out in the same minute it
  entered (very tight stop). No implementation error found; the loss looks like a genuine absence of edge
  after costs, with stops tight relative to fees/slippage. This is a hypothesis, not a proven cause.
- **Baselines**: not re-run - the Stage 4 development baselines above (no_trade 0; buy_and_hold liquidated,
  -190 % with funding; random entry mean -8.3 %, p5 -56 %, p95 +61 %) apply to the same window, but use
  different sizing (full notional, 24 h holds) than S4's 1 % risk, so they are context, not a ranking.
- **Not done**: windowed robustness (pointless while the full-period result is negative; one run is ~20 min),
  forward/paper wiring (needs calendar time and a worthwhile strategy), `TrackRecord`/grade. S4 stays
  `EXPERIMENTAL`. No parameter was tuned on this period; any v2 must be pre-registered in spec section 11
  and validated on the validation period, never chosen from these numbers.
- **Not claiming profitability** (CLAUDE.md rule 6): this is a losing development result, reported as is.

**Phase 7b, part 2b - unchanged S4 v1.1 on validation and forward (done, 2026-10-09; owner asked to test other years).**
Same code and parameters as the development run, nothing tuned. The sealed test period (2025-01-01 ->
2026-07-01) was **not** run: it needs the owner's explicit go and is logged permanently; running it for S4 now
would use it up for any later S4 variant.
- **Validation (2023-07-01 -> 2025-01-01, 13 200 h)**: 58 signals, **40 trades**, win rate **17.5 %**, total
  return **+0.73 %** (10 000 -> 10 073), max drawdown **19.7 %**, Sharpe 0.10. Gross +1 288 USDT, fees+slippage
  1 148, net +73. LONG: 17 stops (-2 073), 5 TP (+2 982); SHORT: 16 stops (-1 847), 2 TP (+1 011). By half-year:
  2023H2 14 trades -226; 2024H1 15 trades -552; 2024H2 11 trades +851.
- **Forward (2026-07-01 -> 2026-10-08, true out-of-sample, 2 378 h)**: 7 signals, **4 trades**, +0.46 %, win rate
  25 %, max drawdown 3.0 %, Sharpe 0.27 - a sample far too small to conclude anything.
- **Reading**: development -20.5 % (108 trades), validation about breakeven (+0.7 %, 40 trades). The signal rate
  fell from ~0.7/week to ~0.45/week. The gross edge is positive in all three periods but costs take most or all
  of it; the validation result is statistically indistinguishable from zero. S4 is **not shown to be profitable**;
  grade stays EXPERIMENTAL.

**Phase 7b, part 2c - exit-management study and a CFD cost profile (done, 2026-10-09; owner questions: are costs
too high, would breakeven at +1 R / partial at +2 R help, broker is JustMarkets MT5 BTCUSD).**
- **Cost check**: Stage 4 costs are computed correctly for a Binance USDT-perp (taker 5 bps/side + slippage ~= 19 bps
  round trip, ~0.26 R per S4 trade). The owner's venue is a CFD: new profile `config/costs_cfd_justmarkets.yaml`
  (Pro account, no commission, ~2.5 bps round-trip spread from a public 2025 test, swap-free, stress x4). Default
  `config/costs.yaml` untouched; every Stage 4-10 result still uses it.
- **Study** (`scripts/s4_variant_study.py`, pre-registered in `docs/strategy_impulse_retest.md` section 11 before
  results): unchanged v1.1 signals replayed on 1m bars by the Phase 4 `track_signal`, now extended with
  `breakeven_at_r` (stop to entry from the bar after +r R is reached; 3 new tests in `tests/engine/test_paper_tracker.py`).
- **Result**: breakeven (A, B) and fixed +2R/+3R targets (C, D) did not beat the unchanged exits on development
  (selection rule picked V0). V0 under CFD costs: development +12.3 R (+7.7 %, 127 trades), validation +19.5 R
  (+18.3 %, 58 trades); under perp costs -23.3 % and -2.6 %; under the x4 spread stress about zero combined.
  Costs are the swing factor, not exit management. Full tables in section 11 of the spec.
- **Not done / honest limits**: sealed test untouched; spread unverified on the owner's terminal; tracker has no
  funding (fine for swap-free CFD); results are replays of signals, not a full engine run with CFD costs; S4 stays EXPERIMENTAL.

**Strategy S5 "Squeeze-Breakout" (done, 2026-10-09; second new strategy of the owner-requested expansion, first of the
planned S5 -> S6 -> S7 -> ML-filter order).** Spec `docs/strategy_range_breakout.md` written before code (fixed parameters:
24-bar 1h range <= 4 ATR, 15m close beyond the edge + 0.1 ATR, 4h `ema_slope_50` direction filter, stop at the
range middle -/+ 0.25 ATR, targets 1.0/1.5/2.0 x range width). Code: `engine/strategy_s5.py` (math),
`backtest/strategy_s5_provider.py` (adapter, hourly cache, same `backtest -> engine` pattern a fourth time),
18 new tests + 5 static-boundary tests; `scripts/s4_variant_study.py` now records either strategy.
- **Result, unchanged v1**: development 208 trades (1.1/week), win 35.6 %, **-42.0 %**, maxDD 43.5 % (engine, perp costs); -26 %
  with CFD costs. Validation 97 trades (1.2/week), win 45.4 %, **-8.1 %** (engine); +1.4 % with CFD costs, -4.6 % under stress.
- **Verdict**: signals are frequent but the average trade loses even with cheap CFD costs; no edge shown; EXPERIMENTAL.
  No tuning.

**Strategy S6 "Trend-Pullback" (done, 2026-10-09; third strategy of the expansion).** Spec `docs/strategy_trend_pullback.md` first
(fixed: 4h slope direction, pullback of the last 8 1h bars to EMA(20) within 0.25 ATR while the close holds on the trend
side, 15m close beyond the previous 4 bars' extreme, 8 h cooldown, stop under the pullback low and never tighter
than 1 ATR, targets 1.5/2.5/4.0 R). Code `engine/strategy_s6.py`, `backtest/strategy_s6_provider.py`, 28 new tests.
- **Result, unchanged v1**: development 342 trades (1.9/week), win 40.9 %, **-22.6 %** (engine, perp costs), **+5.7 %** with CFD costs;
  validation 211 trades (2.7/week), win 41.7 %, **-13.5 %**, **+4.1 %** with CFD costs; about zero or slightly negative under spread stress.
- **Verdict**: the most frequent signal so far (closest to the owner's 3-4/week) but the edge is ~+0.025 R per trade on CFD costs,
  inside noise; EXPERIMENTAL.

**ML signal filter on S4/S5/S6 (done, 2026-10-09; no value).** Pre-registered in `docs/ml_signal_filter.md` before training:
L2 logistic regression on Stage 3 `required` features + strategy/side/stop distance/TP1 R, purged and embargoed expanding
walk-forward on development (`scripts/ml_signal_filter_study.py`), then one frozen application to validation against a
2000-draw random-rejection control. Development out-of-fold ROC-AUC 0.57; validation ROC-AUC 0.62; kept mean R +0.095 vs
+0.074 unfiltered but far below the random-rejection 95th percentile (+0.198) -> **not useful**, not adopted. The model mostly
sorts by strategy. Sealed test untouched. Remaining ideas in the agreed order: S7 (mean reversion in ranges); the realistic
conclusion so far is that none of S4-S6 nor an ML filter on top gives a reliable edge.

**Forward evaluation of S4/S5/S6 (wired 2026-10-10; first run).** New command `arven paper strategies` (`src/arven/paper/strategies_forward.py`,
`scripts/run_paper_strategies.bat`, `docs/RUNTIME_OPERATIONS.md`): REST update, the same provider objects as the backtest asked at every
15m close, signals appended to `data/signals/<strategy_id>/`, every signal resolved on 1m bars under the CFD (broker) cost profile with the
full 50/30/20 ladder, summary in `data/paper/strategies_summary.json`. Signals are independent (no one-position gating), so counts are
higher than in the backtest. 8 new tests. **Not scheduled automatically** and no Telegram token is configured (`dry_run: true`), so nothing
runs unattended yet.
- **First run, 2026-07-01 -> 2026-10-10 (~14 weeks, true out-of-sample)**: S4 7 signals (-0.13 R mean, 14 % win), S5 31 (-0.34 R, 35 %),
  S6 161 (-0.11 R, 41 %; 11 signals/week without the backtest's one-trade-at-a-time gating). All three negative so far.
- **Agreement hypothesis**: signals confirmed by another strategy within 4 h: n = 49, -0.33 R (37 % win); lone signals n = 149, -0.09 R.
  **Not supported** by the first forward data (the earlier dev/val impression was a post-hoc cut).
- Small sample, ladder exits (not the V0 single exit of the studies), spread-only costs: not a verdict, not evidence of profitability.

**Phase 8a - read-only HTTP API (done, 2026-10-10; Phase 8 split into 8a API / 8b React app / 8c browser tests, as 9a/9b before).**
`arven web` (`src/arven/web/`: `app.py`, `service.py`, `journal.py`) serves FastAPI on `127.0.0.1:8000` only (`--allow-remote` is
required for anything else). Endpoints: `/api/health`, `/api/overview` (data freshness, runtime heartbeat, signal counts, forward
summary), `/api/candles` (1m/5m/15m/1h/4h from the stored database), `/api/signals` (+ detail and updates), `/api/strategies`,
`/api/screener` (single symbol, honest note: multi-symbol is Phase 9), `/api/research` (backtest/paper/WFO manifests incl.
`touched_test_set`), `/api/journal` (the only write path: the owner's manual trades, separate file, R stats), `/api/telegram`
(status only, never the token), `/api/stream` (Server-Sent Events), `/api/docs`. CORS limited to localhost origins; no endpoint can
place an order or write market data (checked by tests). Dependencies added with the owner's explicit approval in the master prompt:
`fastapi`, `uvicorn`, `httpx` (pyproject). 13 new tests (`tests/web`), run against a temporary data directory; also queried live
against the real database (overview, signals, candles, telegram status all returned real data; the 'runtime' block honestly shows no
heartbeat because the always-on runtime is not running). Not built yet: the React front end (8b) and Playwright/Lighthouse checks
(8c; Playwright is not in the master prompt's approved dependency list, so the owner is asked before it is installed).

**Phase 8b - the web app (done, 2026-10-10).** `web/` (Vite 8 + React 19 + TypeScript + Tailwind 4 + `lightweight-charts` + Framer Motion; all
approved in the master prompt). Build: `cd web && npm install && npm run build`; then `arven web` serves it at `http://127.0.0.1:8000`
(dev server: `npm run dev`, proxies `/api`). Pages: Overview (data freshness, runtime heartbeat, signal counts, forward results with the
small-sample warning and the agreement hypothesis), Live signals (list + candle chart with entry/stop/TP ladder lines and a signal marker,
countdown to the next 15m close, reasons, risk checks, update timeline), Screener (single symbol, honest note), Charts (5m/15m/1h/4h with all
signal markers), Strategies (forward stats per strategy plus a clearly sourced static table of the offline development/validation results),
Journal (manual trades, R stats, delete), Research lab (stored backtest/paper/WFO manifests with the `touched_test_set` flag and hashes),
Settings (Telegram status without secrets, EN/RU, dark/light). Design: near-black canvas with gold and emerald/crimson semantics, glass
cards, tabular monospace numerals, skeleton loaders, designed empty/error/offline states, keyboard shortcuts (1-8, T, L), skip link,
`prefers-reduced-motion` respected, bottom tab bar on narrow screens. `tsc --noEmit` and the production build pass. **Verified visually**
with headless Chrome screenshots of every page against real data (199 real signals, real candles); one real defect found and fixed that way
(wide tables forced horizontal page scroll at phone width). The honest banner "paper simulation, not advice, not evidence of
profitability" is on every page. Not done: automated browser tests, Lighthouse scores and committed screenshots (Phase 8c, needs the owner's
OK for Playwright: it is not in the master prompt's approved dependency list). `data/` and `web/dist` are git-ignored.

**Phase 8c - browser tests, Lighthouse, screenshots (done, 2026-10-10; Phase 8 complete).** Playwright (`@playwright/test`) and
`lighthouse`/`chrome-launcher` added to `web/` as dev dependencies with the owner's explicit OK; they drive the **installed Google
Chrome** (`channel: "chrome"`), so no browser was downloaded. The server under test is `scripts/web_fixture_server.py`: the real
`arven.web` API over a temporary, clearly synthetic data directory (never the real database). `web/e2e/app.spec.ts`: **51 passed**
(desktop and phone-emulated Pixel 7): every page renders without console errors and shows the honesty banner, no horizontal page
scroll on any page, overview table and small-sample warning, signal list/selection/filter and chart overlays, keyboard shortcuts,
language/theme persistence, journal add and delete, the offline state, the lab's sealed-test flag, no bot token ever shown. Run with
`cd web && npx playwright test`. **Lighthouse** (`web/e2e/lighthouse.mjs`, results in `docs/lighthouse.json`, all 8 pages, mobile and
desktop presets): performance min 95, accessibility min 95, best-practices 100, SEO 100 - gate (>= 90) met. First measurement on mobile
was 77-81 for performance: fixed by lazy-loading every page and the chart library (main bundle 554 kB -> 233 kB) and by replacing
Framer Motion with CSS transitions (the package was removed again; a small deviation from the master prompt's stack, taken for the
performance gate). Screenshots of all pages in `docs/screenshots/` (fixture data, stated in its README). Also found by the tests: nothing
in the app itself; the failures during development were test-selector mistakes.

**Web app redesign "wow pass" (done, 2026-10-10; owner feedback: the first interface was too plain, more animation and beauty, and it must
explain ARVEN to teachers who will not grasp the functionality).** New first page **Home**: animated constellation hero with a typing
tagline, count-up facts, three pillars (Analyse / Decide / Protect), an animated **pipeline** of the seven steps a signal travels, five
"honest by design" cards, and the **live equity curve in R** drawn from the real forward paper trades (currently -29 R: the honest result
is shown, not hidden). A **guided tour** (button in the header, 7 steps, keyboard-navigable) opens each page in turn and explains it in two
sentences. Overview became a command centre (radial data-freshness gauge, pulsing runtime dot, count-up counters, equity curve, per-strategy
cards with animated win-rate bars); signals got an animated risk/reward ladder and pulsing open markers; strategies got an animated
development/validation bar chart; cards tilt and light up under the pointer; on-scroll reveals; slow aurora background; dark is the default
look (light one click away); EN/RU. All motion respects `prefers-reduced-motion`. Backend support: the forward summary now carries a `trades`
series (`trade_log`, 1 test). Browser tests updated and extended (home, tour): **59 passed**; Lighthouse after the redesign: performance min
92 (mobile) / 99 (desktop), accessibility min 95, best practices 100, SEO 100 - an expensive CSS blur on the background was removed to
hold the gate. Screenshots: `docs/screenshots/` (synthetic fixture) and `docs/screenshots/real/` (the real database, dark theme, desktop and
phone, including full-page captures of Home and Overview).

**Chart history fix (2026-10-10, owner report: "the market does not load when I scroll left").** The chart components loaded a fixed 220-500
bars and re-created themselves on every data change, so panning left showed an empty area. Now `CandleChart` keeps its view and the new
`useCandleFeed` hook prepends 500 older bars from `/api/candles?before=` whenever the view comes within 25 bars of the oldest loaded one (and
refreshes the newest bars every 30 s); a signal's chart first loads back to 6 h before the signal and is centred on it. Browser test added
(dragging back in time issues older-history requests; the fixture now holds 1300 bars per timeframe so paging is exercised): 60 tests.

**The first three strategies in the UI and under broker costs (2026-10-10, owner question: "why only S4-S6 everywhere, were S1-S3 forgotten?").**
They were not forgotten but they run in a different system: `trend_momentum`, `breakout` and `mean_reversion` vote inside the hourly Stage 5
pipeline (decision engine + risk engine), which writes run artifacts, while the signal store and the forward tick used by the UI only hold the
event-driven S4-S6. The web app now shows them as one card "S1 + S2 + S3 (Stage 5 pipeline)" next to S4-S6 (latest hourly paper run, from
`/api/research`) and as a bar group in the offline-studies chart. They were also never "good" in the data: Stage 5 development -20.3 % (111
trades), Stage 7 walk-forward negative in all 16 windows (mean -11.2 %), forward paper -17.6 % (92 trades, 101 days) - all under exchange
costs. New today: the same pipeline re-run **under the broker (CFD) cost profile** via `arven --config-dir <copy of config with
costs_cfd_justmarkets.yaml as costs.yaml and an absolute data_dir> backtest run --provider pipeline`: development **-17.4 %** (410 trades,
win 35.9 %, profit factor 0.87, **gross -11.1 % before costs**), validation **-9.9 %** (530 trades, win 34.7 %, profit factor 0.93, gross -1.6 %).
So even before costs they show no edge. (Trade count differs from the old 111 because cheaper costs keep the equity path above the risk
engine's halts; same code, different cost path.) Sealed test untouched.

**Strategy S7 "Trend-Break Fib Retest" - the owner's own method: spec + detector + review page (2026-10-10; no backtest yet).**
The owner explained his real method (chat + annotated TradingView screenshots; his older screenshots in `Pictures/Screenshots` were
sampled to understand it - many are unrelated; nothing from them was used as data). Spec `docs/strategy_s7_trend_break_fib.md` (approved):
descending line with clustered touches -> break that closes at/above the last touch high (and, after a sideways range, above the range top
as well; the two closes may be different candles) -> Fibonacci from the last low before the break (0) to the highest close of the break leg
(1), level 1 frozen at the first 0.236 pullback -> entry zone 0.5-0.618 -> confluence score from order block / FVG / iFVG / prior swing levels.
10 pre-registered variant questions (25 variants) for the later evaluation. Implemented: `src/arven/engine/strategy_s7.py` (pure, causal state
machine; shorts are the mirror; 7 hand-built tests incl. truncation-causality and the range rules), `scripts/s7_review_export.py` (development
setups with candles only up to the arming bar), API `/api/s7/review` + `/api/s7/labels` (owner verdicts, the second write path next to the
journal), web page "S7 check" (chart with line, touches, range, Fibonacci, zone; Y/N/U verdicts, notes). Detector development counts after two
significance rules: 4h 45, 1h 248, 15m 955 setups.

**S7 owner check, round 1 -> detector v2 (2026-10-10).** The owner marked all 100 exported setups (yes 23 / no 13 / unsure 64, with
notes; archived in `data/s7_review/round1/`). Turned into rules (spec §2.1, §2.7, §3, §8, variant log): crooked lines rejected (no wick
more than 0.8 ATR through the line); a bar running through the whole entry zone with a bearish body >= 1 ATR or volume >= 2x the 20-bar
median cancels the setup (owner's rule, thresholds the analyst's - the owner had no exact numbers; `detect_setups` now takes optional
`volume`); legs that rise above the line's first anchor ("all previous highs broken" - the owner is unsure) are skipped by default and
pre-registered as variant 11 (27 variants in total now); `zone_touched_at_arm` flag, and the entry search will start inside the arming bar.
Long ranges were *not* made a rule (present in many "yes" setups too). v2 keeps 21/23 "yes" and 4/13 "no" (three crooked lines and one
"not it" remain). Development counts: 4h 21, 1h 128, 15m 560. 5 new hand-built tests (12 S7 tests in total). Round-2 sample exported
(4h 21 = all, 1h 40, 15m 30; seed 7, volume now in the candles).

**S7 owner check, round 2 (2026-10-11).** 91 setups marked yes 17 / no 7 / unsure 67; "unsure" did not shrink, so labelling stopped - the
evaluation decides the rest. Two contradictions with the spec, both kept as pre-registered variants by the owner's choice: variant 12 (the
break is the first close beyond the line) and variant 13 (the line starts at the window's major high); 29 variants in total. "Late entry"
notes are covered by the entry search inside the arming bar; ranges and "the high kept updating" become analysis dimensions, not rules.
Development counts baseline 4h 21 / 1h 128 / 15m 560 (variant 12: 16 / 94 / 395; variant 13: 21 / 126 / 496); 4h cannot reach the
100-trade minimum. 14 S7 tests. Round-2 labels in `data/s7_review/labels_*.json`.

**S7 evaluation stage (2026-10-11; owner: "start").** New: `src/arven/engine/strategy_s7_plan.py` (pure plan: E1-E4 entries, S1-S3
stops, TP1 fib 1.0 / TP2 nearest swing resistance in fib 1.272-1.618 / TP3 fib 2.0 at 50/30/20 %, pre-entry cancellations),
`src/arven/backtest/strategy_s7_sim.py` (execution: entries only after the arming close, conservative limit fills that must trade
through the spread, stop-in-fill-bar = loss, exits via the existing 1m `paper_tracker`, one trade at a time), `scripts/s7_study.py`
(pre-registered one-at-a-time selection, CFD/perp/stress, random-entry control, breakdowns; full record incl. source SHA-256 in
`data/s7_study/development.json`). Detector additions: re-arming after a close above level 1, variant 3 (FVG), variant 14 (zone
convention - the owner chose "test both" after an inconsistency was found: the detector's zone was the 50-61.8 % retracement while the
spec's own fib definition and the review page's lines meant 38.2-50 %), recorded `atr`/`limit_618`/`level1_moves`. **Design change**
(spec §3): the entry search starts at the arming *close*, not inside the arming bar - otherwise arming-bar rules evaluated at its close
would discard losing intrabar entries with hindsight. S7 tests now: detector 17, plan 6, simulator 15, boundaries 3 (41), plus the
legacy-module boundary list; an independent re-derivation matched all 42 baseline E1 entries; full suite 2256 passed / 13 skipped.
- **Development result** (spec §10): 21 configurations; selected 15m / FVG / freeze 0.382 / E3 / S1 / shallow zone. CFD: 167 trades,
  win 55.7 %, mean +0.285 R, +47.6 R (+58.5 % at 1 % risk, max DD 8.5 %); CFD spread x4: +23.4 R; perp: +9.9 R; perp stress: -7.2 R.
  Random-entry control (same geometry, 200 draws) mean -0.039 R, 95th pct +0.110 R; buy-and-hold +323.7 %. The baseline config (1h,
  all defaults) had only 42 trades (+4.7 R CFD). In-sample best-of-21 and cost-sensitive: **not evidence of profitability**.
- **Validation (2026-10-11, run once with the owner's go, commit `0ce16d6`, clean tree; spec §11):** 102 trades, win 44.1 %, mean
  -0.030 R, **-3.05 R** under CFD costs (-3.8 % at 1 % risk, max DD 14.3 %); CFD spread x4 -20.8 R; perp -30.1 R; perp stress -35.0 R.
  Random-entry control mean -0.056 R (95th pct +0.148 R); buy-and-hold +207.1 %. **The development result did not replicate**; S7
  stays EXPERIMENTAL, nothing is re-tuned after validation (pre-registered rule). Every run is logged in `data/s7_study/evaluations.log`.
  Sealed test untouched. Realistic conclusion, as for S4-S6: no reliable edge shown.

**Owner direction, cost check, $ account replay and the "S7 trades" page (2026-10-11).** The owner does not want new strategies
added endlessly (a drafted "S8" was dropped, never committed) but to learn *when* S7 works and when not, and asked to re-check costs,
to see results in dollars and to see S7's trades on the site.
- **Costs re-checked** (same S7 trades under zero / CFD / perp costs): development +52.5 / +47.6 / +9.9 R; validation **+0.5** / -3.1 /
  -30.1 R. Even with *zero* costs validation is flat, so costs did not cause the failure; the CFD spread (1.25 bp per side, an
  unverified public estimate) costs ~0.03 R per trade; perp costs (5 bp taker + slippage per side) cost ~0.2-0.3 R per trade because
  the median stop is only ~0.6-0.8 % of price.
- **Dollar replay**: `src/arven/backtest/account_sim.py` (pure; 4 hand-computed tests) - $1000, 1 % of current equity at risk, size
  rounded down to 0.01 BTC lots, minimum lot used only while its stop loss is <= 5 % of equity, else skipped (lot size/step are
  assumptions to verify on the owner's terminal). S7 selected config, CFD: development $1000 -> $1483 (max DD 6.7 %), validation
  $1000 -> $928 (-7.2 %, max DD 13.0 %), no trade skipped.
- **Site**: `scripts/s7_trades_export.py` -> `data/s7_study/trades_<period>.json`; read-only `GET /api/s7/trades?period=`
  (development|validation only; 1 test); new page "S7 trades" (`web/src/pages/S7Trades.tsx`: summary, balance curve, trade list, chart
  with entry/stop/targets/zone/trendline and entry/exit markers; EN/RU). Typecheck/build OK, 68 browser tests pass (page added to the
  e2e list), checked visually on real data with no console errors.
- **SMC zones vs outcome** (zones the detector already records in the entry area; analysed, not yet a rule): trades with an
  **iFVG** in the zone: development 69 trades +28.9 R, validation 41 trades **+11.9 R**; without iFVG: +18.7 R / **-15.0 R**. Three or
  more zone types: +25.5 R (56) / +7.7 R (32); two or fewer: +22.1 R / -10.8 R. Plain FVG is unstable (+38.7 / -4.5 R); SnR levels
  are present in almost every trade. Looked at *after* validation, so this is a lead to be tested (walk-forward + forward data), not
  evidence.
- **Web redesign v2 (owner asked for a clearer, "wow" site without breaking anything).** App shell: a fixed, grouped sidebar
  (Home / Market / Strategy S7 / Research / Personal) instead of 11 top tabs, a slim top bar (breadcrumb, Ctrl+K page search, tour,
  language, theme; the honesty banner stays in the header), a phone drawer + 5-button bottom bar, page transitions. Charts: "fit the
  whole trade", full screen (Escape closes) and an OHLC crosshair legend; lines/overlays/markers are now re-applied if the chart is
  re-created. "S7 trades": verdict buttons correct / wrong / unsure (Y/N/U) with a note, stored by the new write path
  `POST /api/s7/trade_labels` (`data/s7_study/trade_labels.json`; the read-only-surface test lists it), filters (winners / losers /
  not marked / marked wrong), SMC zones drawn per kind, the first view fits the whole trade. Hash routes and keyboard shortcuts are
  unchanged. Typecheck/build OK; all 68 browser tests pass (a card-header overflow at 1280 px was found and fixed); checked visually on
  desktop and phone with no console errors. Lighthouse was not re-run.
- **Next (proposal, not started):** "when does S7 work" as a walk-forward study - rules learned only from the past, applied to the next
  unseen window, repeated through 2020-2024 - rather than re-testing on the same validation period.

**Live signal loop - every strategy in real time (2026-10-11; owner: "finish the project to the point where it gives signals
in real time, leave the strategies as they are, keep it possible to change strategies later").** Operations, Telegram set-up and
how to change/add strategies: `docs/LIVE_SIGNALS.md`. Strategy rules were not changed; this is plumbing around them.

- **One process, `arven live run`** (`src/arven/live/`).
  - Every 20 s it REST-updates the data. At each 15m close (5 s later, and only once the close's 1m bars are stored) it lets
    every enabled strategy scan, stores new signals once, replays every stored signal on 1m bars (filled / TP / stop moved /
    cancelled / closed, net R, CFD costs), and queues Telegram alerts (only for signals/updates < 6 h old).
  - It writes `strategies_summary.json`, runs the Stage 8 hourly paper run itself (one DuckDB writer), drains the Telegram
    outbox, answers bot commands, and queues a daily summary and system alerts (start / stale data / 3 failed ticks).
  - Heartbeat `data/live/heartbeat.json`, state `data/live/state.json`, log `data/live/live.jsonl`.
  - Stale data (newest 1m bar > 180 s old) stops the tick before any strategy is asked (rule 5).
  - Restart-safe: per-strategy cursors, persisted loop state, catch-up after downtime. A failing strategy keeps its cursor while
    the others carry on.
  - CLI: `arven live run|tick|status|heartbeat`. `arven paper strategies` is now an alias of `arven live tick`, and the old
    `run_strategies_tick` is removed. `scripts/run_live.bat` plus a Task Scheduler recipe are in `docs/LIVE_SIGNALS.md`.
- **Changeable strategies.**
  - `config/live.yaml` lists every strategy: `id`, `kind`, `enabled`, `version`, `params` (validated at start-up; an unknown
    kind or key is an error).
  - `src/arven/live/registry.py` maps `kind` to the code. A strategy is a small class with `scan` / `resolve`
    (`src/arven/live/base.py`).
  - S7 takes the S7 study's configuration keys (the development selection is in the file). Crowded Shorts takes its four
    pre-registered values. S4-S6 keep their pre-registered constants in code.
  - Signals carry the strategy version and a hash of its params.
- **Adapters reuse the research code** (rule 8; a static test checks it).
  - S4-S6: their providers, exactly as the forward evaluation used them, with the same signal store and cursor file, so their
    history continues.
  - S7: the detector over all 15m bars since 2020. A setup is announced at its arming close as a **limit** signal (fib 0.5,
    stop S1, TP ladder, expiry) and resolved by `simulate_setup`.
  - Crowded Shorts: new pure rules in `src/arven/engine/strategy_crowded_shorts.py` plus execution in
    `src/arven/backtest/crowded_shorts_sim.py`. A test reproduces the research script's block logic verbatim on random data.
  - **Verified on real data (forward 2026-07-01 -> 2026-10-11):** the live code reproduced all 21 S7 research trades and all
    3 Crowded Shorts trades with bit-identical net R. Live S7 has 26 closed and 6 cancelled signals, -10.48 R. The research
    table's -7.28 R applies one-trade-at-a-time; live tracks every signal on its own, like S4-S6.
- **Open interest is now REST-tailed** (changes Stage 8 D2; `architecture.md` updated). Crowded Shorts needs `oi_z`.
  - Source: Binance public `futures/data/openInterestHist` and the long/short ratio endpoints; 30 days of history, 500 rows a
    call.
  - Measured on 500 overlapping rows against the bulk `metrics` files: open interest identical, ratios equal to the REST's
    4 decimals. The REST timestamps are bulk `create_time` + 5 min (taker ratio: same time), so rows are stored under the
    bulk convention and never overwrite bulk rows.
  - After the first tick `oi_available` = 1 on every forward hour and live `oi_z` is finite.
- **Small additive core changes.**
  - `EngineSignal` gained `entry_type` (`market` | `limit`) and `valid_until_ms`. Both are left out of the hash at their
    defaults, so all 201 stored S4-S6 signals keep their ids (checked).
  - `EngineSignal` also allows an empty TP ladder when the signal has a time exit (Crowded Shorts).
  - `SignalUpdateKind.FILLED` added.
  - The S7 simulator's outcomes now also carry the fills with their tracked events and the time of a cancellation (research
    numbers unchanged; S7 tests pass).
  - Web API statuses: pending / open / partial / closed / cancelled, plus entry type and expiry; the Signals page shows them
    (EN/RU).
  - Telegram texts spell out limit entries with their expiry and time exits, and show times. Also fixed the old "vv1" version
    display.
  - README rewritten (it still said "Stage 1").
- **Tests:** 31 new in `tests/live/` (rules, execution hand-computed, research parity, config/registry, S7 outcome mapping, the
  tick on a synthetic DB with fake strategies, the loop with fake dependencies, module boundaries), plus REST open interest (3),
  signal object (3), web status (1), Telegram text (1).
- **First real run:**
  - `arven live tick`: all five strategies ran. S7 back-filled its 32 forward signals and Crowded Shorts its 3; no new live
    signal yet; tick ~85 s, mostly the S7 detector.
  - Then `arven live run` ran as a soak test in this session: every 15m close evaluated once, each tick `ok` in ~85-110 s
    (slower while the test suite ran), the hourly paper run done inside the process, heartbeat every 20 s.
- **Verification:** full suite **2312 passed, 13 skipped** (2271 + 41); web typecheck/build OK; Playwright **68 passed**
  (4 screenshot tests skipped as before).
- **Not done, needs the owner:**
  - No real Telegram token/chat id yet: alerts are queued, but nothing is sent until `.env` + `dry_run: false`.
  - (Done with the owner's go, 2026-10-11 14:43 UTC: Task Scheduler 'ARVEN Live' installed - at log-on, restart on failure -
    and 'ARVEN Paper Run' disabled; the scheduled process resumed from the saved state and evaluated the 14:45 close `ok`.)
  - The master prompt's 14-day continuous forward-operation gate has not been run.

**Live process hardening (2026-10-16).** From 2026-10-11 to 2026-10-16 the live loop:
- handled a network outage correctly (2026-10-13: Binance unreachable, `getaddrinfo failed`; ticks `stale`, no signals;
  caught up after the network returned, one new S6 signal);
- then stopped for ~46 h: the console window of `run_live.bat` was closed on 2026-10-14 (task result `0xC000013A` =
  Ctrl+C / window closed). Windows does not treat that as a failure, so "restart on failure" never fired. The
  laptop's Modern Standby also paused it at times.

Fixes:
- The task now runs `pythonw` without a window (`arven live run --log-file`).
- A second trigger re-checks every 5 minutes.
- A single-instance OS lock, `data/live/live.lock` (`src/arven/live/instance.py`, tested): a second copy exits at once
  (checked by hand).
- A present `live.stop` keeps the process stopped instead of being deleted at start.

The restarted process caught up the missing two days in one tick: 6 new signals (S5 x3, S6 x3), 10 updates. Also added
`scripts/run_web.bat` (starts the web app in its own window). The laptop's sleep settings remain the owner's choice
(`docs/RUNTIME_OPERATIONS.md`, "Power settings").

Later on 2026-10-16:
- The laptop slept from 02:21 to 08:26 UTC. On waking, the first tick was `stale` (network not up yet), and the
  following polls caught up. This is the expected behaviour.
- The web app was down again: the console window of `run_web.bat` had been closed. It now has its own Task Scheduler
  task, **"ARVEN Web"**, built like "ARVEN Live":
  - `pythonw -m arven web --log-file data\live\web_process.log`, without per-request access lines;
  - a 5-minute watchdog trigger;
  - an OS lock `data/live/web_<port>.lock`, because Windows lets a second socket bind the same port. A second copy
    exits at once (checked by hand).
- `--log-file` logs (live and web) over 5 MB are moved to `<name>.1` at process start (`open_log`, tested).
- **Backup:** `arven backup` (`src/arven/live/backup.py`, 3 tests).
  - It zips what cannot be downloaded again: `data/signals`, `data/live`, `data/telegram`, the top-level files of
    `data/paper` (not the hourly run directories) and `config/*.yaml`. Lock files are left out.
  - `--with-db` adds a consistent DuckDB copy, taken while holding a read-only connection (DuckDB then refuses a
    writer).
  - It keeps the newest 10 archives (`--keep`) and writes through a `.part` file.
  - First real run: 39 files, 0.1 MB zipped. With the database: 258 MB zipped, 44 s; the live loop was unaffected.
  - It is not scheduled. The owner runs it, or it can be added as a task later.
- **`docs/DEFENCE_DEMO.md`** (in Russian), the master prompt's 10-minute walkthrough: data → features → regime →
  strategies → decision → risk → signal → Telegram → web → honest results, plus likely questions. README links it
  and gained backup and troubleshooting notes.
- **Telegram is live (2026-10-16).** The owner created a bot and put the token and two chat ids (a private chat
  and a group) in `.env`.
  - `arven telegram test` delivered to both chats.
  - `dry_run` was set to `false` and the live process was restarted through the stop file.
  - The start line reads "Telegram: 2 chat(s), sending, token set", and the "live loop started" system alert went to
    both chats (outbox status `sent`).
  - Still to be observed: a real signal or update arriving, and a bot command answered.
- **Known growth:** every hourly legacy paper run writes a full replay of the forward period (~1.6 MB now, and it grows
  with the period), so `data/paper` grows by about 40 MB a day and faster later (197 MB after 149 runs). There is
  plenty of disk (79 GB free), but a retention rule (e.g. keep the newest runs plus one per day) is an open item.
  Nothing has been deleted.

**Improvement pass (2026-10-16, owner: "do all the improvement steps you listed"; no server yet).**
- **S7 detector about 5 times faster, identical results.** `src/arven/engine/strategy_s7.py`:
  - `nan_to_num(ATR)` and the swing lows are computed once instead of per candidate line or setup;
  - the confluence swing levels are filtered with vector comparisons;
  - the line search takes its swings by bisection (`_known_swings`).

  On the real 15m history it fell from 80 s to 14 s, and all 590 (live configuration) + 1567 (defaults) setups are
  field-for-field identical to the previous code. `tests/engine/test_strategy_s7_speed.py` pins each equivalence and
  causality. The first live tick on the new code finished 49 s after its close (it used to take 1.5-2.5 min).
- **Forward review rule** (`src/arven/live/review.py`, `config/live.yaml` `forward_review`, tests hand-computed).
  - Rule: at least 30 closed signals, then a 95 % normal-approximation interval of mean net R: `losing`, `positive`,
    `inconclusive` or `too_few`.
  - It only flags. The verdict is in `strategies_summary.json` (`review`), on the web Strategies page (EN/RU) and in
    the weekly report.
  - The thresholds are textbook values, set when S6's numbers were already visible, so this is a monitoring rule.
  - First verdicts: S5 inconclusive [-0.65, +0.11]; S6 inconclusive [-0.33, +0.04] (167 closed, -24.5 R);
    Crowded Shorts, S4 and S7 too few.
- **Weekly forward report** to Telegram on Mondays with the daily summary (`weekly_report_weekday`,
  `format_weekly_report`, tested).
- **Daily housekeeping in the live process** at 01 UTC (`config/live.yaml` `maintenance`, `src/arven/live/maintenance.py`,
  tested):
  - a backup with the database, keeping 7;
  - retention of hourly paper-run directories: the newest 48 plus the last of each day. `runs.jsonl` keeps every entry.
    The Streamlit dashboard lists only runs whose directory exists.
  - A failure is alerted once, not retried every poll.
  - First run, 2026-10-16 10:41 UTC: backup 260 MB; 87 old run directories removed (120 MB freed), 58 kept.
- **Tests no longer see the real `.env`** (`tests/conftest.py` autouse fixture). After the owner created `.env`, a
  Telegram test had started reading the real token. Tests can now never reach a real chat.
- **Server deployment prepared** (no server yet): `deploy/linux/arven-live.service`, `deploy/linux/arven-web.service`
  (systemd, restart always), and `docs/DEPLOY_SERVER.md` (in Russian: VPS choice, Python 3.13, moving code and
  data, `.env`, switching the laptop off first, SSH tunnel to the site, updates).
- **Web:**
  - The Strategies page shows the verdict, the 95 % interval and the max drawdown.
  - The trade viewer moved below the strategy cards: mobile Lighthouse performance on that page had fallen to 89
    since the viewer was added on 10-11; it is now 90-91.
  - Lighthouse re-run: performance min 90, accessibility min 95, best-practices 100, SEO 100.
  - Playwright: 72 passed (2 new tests).
- **`docs/RESULTS_FOR_THESIS.md`** (in Russian): every evaluation in one place, with sources, for the thesis.
- **Tests:** full suite 2340 passed, 13 skipped (real-data checks, off by default).

## Full backfill results (per yearly chunk)

Procedure per chunk:
1. `ingest`, split into four quarterly foreground calls, run strictly one at a time with a memory guard.
2. `resample`.
3. Native cross-check on one sample month.
4. `quality`.
5. Report, including a stored-vs-recorded row verification per file.

Memory: ARVEN's peak working set was about 200 MB for ingest steps and 360 MB for the full-period quality run.
Other applications were holding most of the machine's 7.2 GB.

| Chunk | Files ingested | Not avail. | Failed / checksum | Exact dups dropped | Conflicting dups | 1m rows | Funding | OI rows (expected) | OI source gaps | Incomplete derived bars | Cross-check |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2020 | 146 | 244 | 0 / 0 | 35 103 | 0 | 527 040 | 1 098 | 35 103 (from 2020-09-01) | 4 gaps / 33 | 0 | 2020-03 PASS |
| 2021 | 389 | 0 | 0 / 0 | 40 152 | 0 | 525 600 | 1 095 | 104 652 (105 120) | 148 gaps / 468 | 0 | 2021-05: 1 bar differs (source anomaly, below) |
| 2022 | 389 | 0 | 0 / 0 | 0 | 0 | 525 600 | 1 095 | 105 120 (105 120) | 0 | 0 | 2022-11 PASS |
| 2023 | 389 | 0 | 0 / 0 | 0 | 0 | 525 600 | 1 095 | 105 117 (105 120) | 1 gap / 3 | 0 | 2023-03 PASS |
| 2024 | 390 | 0 | 0 / 0 | 0 | 0 | 527 040 | 1 098 | 105 281 (105 408) | 2 gaps / 127 | 0 | 2024-08 PASS (2024-01/02 also) |
| 2025 | 389 | 0 | 0 / 0 | 0 | 0 | 525 600 | 1 095 | 105 117 (105 120) | 1 gap / 3 | 0 | 2025-04 PASS |
| 2026 H1 | 193 | 0 | 0 / 0 | 0 | 0 | 260 640 | 543 | 52 128 (52 128) | 0 | 0 | 2026-06 PASS |

Notes on the table:
- 1m and funding rows equal the expected count in every chunk.
- 2024 counts 390 files because Jan–Feb were already ingested in step 1.
- Every cross-check "PASS" means all bars present on both sides, identical prices and trade counts, and volume within about 1 ULP.

## Final verification (2026-09-28)

- **Tests:** 109 passed.
- **Final quality run** over [2020-01-01, 2026-07-01): 0 errors.
  - 1m: 3 417 120 rows = expected; 0 gaps, 0 duplicates, 0 OHLC/volume violations, 0 unit problems.
  - Derived 5m/15m/1h/4h: all expected counts, 0 incomplete, totals equal to 1m.
  - Funding: 7 119 rows = expected; always 8h; 3 190 rows had 1–47 ms jitter, normalised with the raw value kept.
  - OI: 612 518 rows. The only warnings are the OI gaps below.
  - `source_files.consistency` re-read all 2 285 raw files: 0 inconsistent.
- **Stored vs recorded rows:** 2 321 ingested files, 0 mismatches.
- **Idempotency:**
  - A full-period `ingest` re-run planned 2 529 files: 2 285 skipped, 244 known `not_available`, 0 downloaded.
    Content fingerprints of all tables were identical before and after. The same held for the 2020–2021 re-run before resuming.
- **Clean state:** 0 `.part` files, 0 temp CSVs, 0 WAL files, and no run left in `running`.
  All 26 ingest and 9 crosscheck runs `succeeded`.

**Total rows by table**

| Table | Rows |
|---|---|
| `ohlcv_1m` | 3 417 120 |
| `ohlcv` | 982 422 (5m 683 424, 15m 227 808, 1h 56 952, 4h 14 238; 0 incomplete) |
| `ohlcv_native` | 113 436 (9 sample months × 4 TFs, cross-check only) |
| `funding_rates` | 7 119 |
| `open_interest` | 612 518 |
| `source_files` | 2 565 (2 321 ingested, 244 not_available) |
| `data_gaps` | 157 |

**Storage**

| Item | Size |
|---|---|
| raw zips | 173 MB (klines 145, metrics 28, funding 0.35) |
| Parquet | 202 MB (ohlcv 184.3, OI 26.5, funding 0.1; 43 files) |
| DuckDB | 475 MB (not compacted) |
| `data/` total | 828 MB |

## Gap and anomaly classification (full period)

1. **OI 2020-01-01 → 2020-09-01 (70 272 intervals): expected source boundary.** Binance metrics start on 2020-09-01,
   and the 244 days before are recorded as `not_available`.
2. **OI: 156 real source-data gaps, 634 missing 5-minute snapshots.**
   - By year: 2020 4/33, 2021 148/468, 2023 1/3, 2024 2/127, 2025 1/3.
   - The largest: 2024-02-16 13:35 (125), 2021-02-19 20:05 (63), 2021-06-22 18:30 (52), 2021-06-22 00:25 (37),
     2021-04-27 11:10 (30). Most others are 1–2 snapshots, heavily clustered in 2021.
   - They are source gaps, not pipeline gaps: stored rows equal the raw files exactly, and the 2024-02-16 file was
     inspected and ends at 13:30.
   - All are recorded in `data_gaps` and none are repaired. Stage 3 must turn them into NaN or explicit staleness,
     never interpolation.
3. **Exact duplicate rows in early metrics files: source anomaly, handled deterministically.** 75 255 rows dropped
   in total (all 2020 files and 2021 files up to 2021-05-21), counted per file in `source_files.duplicate_rows_dropped`.
   There were no conflicting duplicates anywhere.
4. **369 zero-volume 1m bars: genuine source bars.** By year: 2020 2, 2021 59, 2022 64, 2023 118, 2024 89, 2025 37,
   2026 0. Reported as info only; relevant for volume features.
5. **Native 5m mismatch at 2021-05-15 00:20 UTC: source inconsistency, preserved, not repaired.**
   - Binance's native 5m bar shows 2 720.216 volume and 24 040 trades.
   - Its 1m bars sum to 2 402.234 and 21 331. The monthly 1m file, the daily 1m file and the REST 1m endpoint all agree
     on this, and REST 5m agrees with the native bar.
   - Our 1m-derived values are kept. Prices are identical.
   - Open item for the later volume-feature decision.
6. **1m OHLCV and funding: no gaps** in the whole period.

## Operational notes

- The first attempt at 2021 ran as a background job and was stopped by Claude Code's memory-pressure protection after
  the chunk had finished. It was verified intact.
- During the resume, a batch of rejected tool calls still started one 2023 Q1 ingest (PID 27556). It was the correct
  next step and a single writer, so it was left to finish, then verified: run `succeeded`, 96 files, and a re-run skipped all 96.
  No concurrent writes happened: a second process was refused by DuckDB's file lock and exited without touching data.
- **The Parquet `export` is the memory-heavy step** (1.56 GB peak working set; global sort of 4.4M bars). It succeeded.
  If memory becomes a problem, per-partition export or a DuckDB `memory_limit` setting could help. Not changed (storage design frozen).

Architecture (`docs/architecture.md`) is approved as the *target* architecture, with these user constraints:
- **Storage:** DuckDB + Parquet only; no PostgreSQL unless a concrete need appears. No Docker.
- **Timeframes:** 1h decision, 4h context, 5m/15m as features.
- **MVP priority:** data, quality checks, features, 3 baseline strategies, rule-based regime, realistic backtesting,
  ML filter, risk engine, LONG/SHORT/NO_TRADE.
- **Deferred:** news, macro, LLM, Telegram, dashboard and paper trading come only after the quantitative core works.
- **Costs:** all configurable.
- **Execution:** none, ever, in the MVP.
- **Priorities:** correctness, reproducibility and leakage prevention over profitability.
- **Process:** explain each stage and the files it changes before implementing; ask before large architecture changes;
  keep the docs current.

## What exists

```
.gitignore                  # .venv, /data/ (root-anchored!), .env, caches, *.duckdb
pyproject.toml              # deps: duckdb, numpy, pydantic, pyyaml, lightgbm; dev: pytest; script `arven`; installed editable (pip -e); pytest path src+tests, marker real_data
config/
  default.yaml              # project, market, data (data_dir, history_start/end, bar + OI availability delays), download (retry policy, crosscheck TFs)
  costs.yaml                # maker/taker fee bps, order types, slippage model params, funding assumptions
  splits.yaml               # dev 2020-01-01→2023-07-01, val →2025-01-01, sealed test →2026-07-01, forward_start 2026-07-01
  features.yaml             # feature version, warm-up factor, every window/period of the v1 features (own hash; not part of AppConfig.config_hash)
  backtest.yaml              # Stage 4: initial equity, leverage, margin/liquidation, lot rules, latency, metric conventions, baseline params (own hash)
  regime.yaml                # Stage 5: trend/vol/stress thresholds, volatility window, dwell bars (own hash)
  strategies.yaml            # Stage 5: decision weights/thresholds + each of the 3 strategies' parameters and regime gates (own hash)
  risk.yaml                  # Stage 5/9a: the 8 risk rules' thresholds/limits incl. macro_blackout_window_hours (own hash; leverage/mmr read from backtest.yaml, not duplicated)
  ml.yaml                    # Stage 6: labels, dataset, walk-forward (D4), hyperparameter grids (D5), calibration (D6), threshold, determinism (own hash)
  macro_events.csv           # Stage 9a: real FOMC/CPI/NFP schedule 2020-01..2027-12 (228 rows), sourced from
                              #   federalreserve.gov and bls.gov; scheduled time only, never the released value
  news.yaml                  # Stage 9b: RSS feed URLs, LLM model (claude-haiku-4-5-20251001), max_items_per_tick
                              #   (cost control), max_tokens (own hash)
src/arven/
  __main__.py, cli.py       # python -m arven {ingest|resample|crosscheck|quality|export|status|features ...|backtest ...}
  core/                     # time.py, timeframes.py, types.py, config.py (Stage 1); series.py (columnar BarSeries/FundingSeries/OpenInterestSeries/MarketInputs
                            #   with available_until + regularized), features_config.py (Stage 3)
                            # signal.py (Signal: the decision->backtest contract), backtest_config.py, splitguard.py (Stage 4)
                            # regime_config.py, strategies_config.py, risk_config.py (Stage 5); ml_config.py (Stage 6)
                            # macro_config.py (Stage 9a): MacroEvent, load_macro_events (CSV -> sorted, UTC-ms
                            #   events; fixed-rule DST conversion, no zoneinfo/tzdata dependency), macro_events_hash
                            # news_config.py (Stage 9b): NewsConfig (feeds, llm_model, max_items_per_tick, own hash)
  features/                 # Stage 3, pure numpy (no I/O, no DB, no later-stage imports; enforced by tests)
    indicators.py             # causal primitives: shift, rolling sum/mean/std/max/min, EMA, Wilder RMA, ATR, RSI, ADX, MACD, Bollinger, Donchian, Parkinson
    asof.py                   # backward as-of join on available_at with staleness limit
    spec.py, registry.py      # FeatureSpec (name, group, source, warmup_bars, required) and the ordered registry + definition hash
    bars.py                   # 5m/15m/1h/4h features, each defined once next to its spec
    futures.py                # funding, open-interest and time features
    builder.py                # build_features(MarketInputs, decision times, config) -> FeatureTable; decision_grid
    checks.py                 # value-range invariants
  data/
    adapters/binance_bulk.py  # Binance bulk layout, SourceFile, plan_files, parse_checksum, has_header
    adapters/binance_rest.py  # Stage 8: public REST klines/fundingRate fetch (no API key, no order endpoints)
    download.py               # Downloader: retries + exponential backoff with jitter, SHA-256 verify, .part + atomic rename
    storage/schema.py         # DuckDB DDL (authoritative schema); schema_version 2 (Stage 9b: + news_items/news_events,
                              #   purely additive, no existing table changed)
    storage/db.py             # connect(), provenance record helpers, run ids, git commit lookup
    ingestion.py              # Ingestor: plan → download → normalise → upsert; one transaction per file; run log
    rest_ingestion.py         # Stage 8: RestIngestor.tail() - REST-tail klines/funding into the same tables,
                              #   staged bulk INSERT OR REPLACE (never row-by-row; see "Operational notes")
    resample.py               # 1m → 5m/15m/1h/4h (exact DECIMAL sums, is_complete flag)
    crosscheck.py             # derived bars vs Binance native klines (ohlcv_native)
    quality.py                # QualityChecker → quality_results, data_gaps
    export.py                 # Parquet export (atomic swap)
    reader.py                 # read-only DuckDB -> MarketInputs (bars with delay applied, funding, OI)  (Stage 3)
                               # + load_1m_bars/load_funding_window (Stage 4): take an AllowedWindow, assert results lie inside it
    storage/feature_store.py  # feature cache: Parquet via in-memory DuckDB (NaN <-> NULL) + manifest.json  (Stage 3)
                               # + read_window_parquet (Stage 4): reads only rows inside a window
  backtest/                   # Stage 4, pure numpy/stdlib (no I/O, no DB, no wall-clock, no strategy/risk/ML imports; enforced by tests)
    types.py                    # frozen records: Order, OrderEvent, Fill, FundingEvent, Position, Trade, EquityPoint, AccountState
    costs.py, margin.py         # fee/slippage and isolated-margin arithmetic (pure)
    accounting.py               # entry/funding/exit state transitions; the accounting equations (docstring)
    marketdata.py                # validated 1m OHLC + funding-grid arrays; gap detection; fingerprint
    clock.py                     # SimulationClock: the only source of "now"; pre-computed decision grid, no wall-clock
    provider.py                  # FeatureView (clock-bound, raises LookAheadError), PortfolioSnapshot, DecisionContext, SignalProvider protocol
    execution.py                 # 1m event-driven Simulator: funding -> liquidation/stop/gap/time-stop -> fill -> intrabar barriers, per bar
    engine.py                    # Backtester: clock loop, decision -> order -> Simulator; BacktestResult
    baselines.py                 # NoTrade, BuyAndHold, RandomEntry (seeded via SeedSequence(base_seed).spawn)
    metrics.py                   # return/vol/Sharpe/Sortino/drawdown/trade stats/turnover/exposure; summarize_distribution (no ranking)
    report.py                    # canonical CSV serialisation, table/result hashes
  runs.py                     # composition root (Stage 4): load_inputs (window-scoped), execute_run/run_baselines, artifact + index writers, verify_run
  regime/detector.py          # Stage 5: RegimeDetector (stateful, causal, hysteresis), classify_series (batch, for reporting)
  strategies/                 # Stage 5, pure numpy/stdlib (no risk/decision/regime/backtest.margin imports; enforced by tests)
    base.py                     # CandidateSignal, Strategy/RegimeGate protocols
    trend_momentum.py, breakout.py, mean_reversion.py   # the 3 strategies (one file each, independently testable)
  decision/
    engine.py                   # DecisionEngine: regime gate -> weighted vote -> conflict/threshold -> ProposedDecision (no portfolio access)
    pipeline.py                  # Stage5Pipeline: implements SignalProvider, wires regime+strategies+decision+risk; DecisionRecord history
  risk/engine.py               # RiskEngine: all 8 rules now implemented (rule 2, macro blackout, added Stage 9a),
                                #   stateful circuit breakers (daily loss/drawdown/cooldown); imports only
                                #   arven.backtest.provider (types), arven.backtest.margin (one pure function) and
                                #   arven.core.macro_config (MacroEvent type), never engine/execution/accounting
  reports.py                   # Stage 5, deliberately outside arven.decision: per_regime_breakdown (post-hoc only, one-directional dependency)
  ml/                          # Stage 6, imports the real regime/strategies/decision/risk (never a copy) + pure Stage 4 cost functions;
                                #   never the execution/accounting engine or duckdb directly (enforced by tests)
    labels.py                    # triple-barrier resolution on 1m bars, net of costs (reuses arven.backtest.costs, not the engine)
    dataset.py                   # replays the real RegimeDetector/strategies/DecisionEngine/RiskEngine with a fixed flat portfolio (D3)
    splits.py                    # purged, embargoed, expanding-window walk-forward folds; date-agnostic (no SplitGuard/config import)
    model.py                     # numpy logistic regression (Newton's method) + LightGBM adapter (deterministic, model_str-based)
    calibration.py               # isotonic regression (stack-based PAVA)
    metrics.py                   # log-loss, Brier, ROC-AUC, PR-AUC, calibration curve/ECE, precision-coverage (pure numpy)
    train.py                     # feature-column selection (D7), walk-forward hyperparameter selection, final fit + calibration
    artifact.py                  # ModelArtifact, full-provenance manifest, save/load/verify (content-hash pattern)
    filter.py                    # MetaFilter (pass/veto only) and RandomFilter (matched-rate control)
  ml_runs.py                    # Stage 6 composition root (mirrors runs.py): dataset -> walk-forward -> final model -> saved artifact;
                                 #   never resolves BacktestPeriod.TEST (checked by test and by a static string scan)
  wfo.py                         # Stage 7, pure functions, no I/O: causal (prior-folds-only) hyperparameter selection,
                                  #   causal (last-4-prior-folds) calibration/threshold selection, fold-10 boundary resolution;
                                  #   imports Stage 6's generate_folds/purge_and_embargo_train_mask/validation_mask/
                                  #   run_walk_forward/select_threshold/fit_isotonic unmodified, never reimplements them
  wfo_runs.py                    # Stage 7 composition root (mirrors runs.py/ml_runs.py): loads dev+val data, builds the
                                  #   combined dataset once, drives the 17-window schedule, runs baseline/ml/shuffled/random
                                  #   backtests per window via the real Stage5Pipeline/Backtester, writes report.json
  paper/
    runs.py                        # Stage 8 composition root: REST tail -> resample -> resolve BacktestPeriod.FORWARD ->
                                    #   build forward-period features in memory -> runs.execute_run (unmodified) -> write
                                    #   data/paper/<run_id>/ + its own runs.jsonl (kept separate from data/backtests/)
  news/                           # Stage 9b, forward-only by construction (no BacktestPeriod concept at all)
    rss.py                          # fetch (via data.download.Downloader) + parse RSS 2.0 (stdlib xml.etree)
    schema.py                       # NewsEvent (the fixed structured-output schema, extra="forbid"), the
                                     #   system prompt, parse_llm_response (tolerates markdown fences, never coerces)
    structure.py                    # structure_item: one LLM call + schema validation -> StructuredResult
    runs.py                         # composition root: fetch -> dedup-store (news_items) -> structure up to
                                     #   max_items_per_tick unstructured items (news_events); all DB I/O
  llm/
    anthropic_client.py             # thin stdlib-HTTP Messages API client (no SDK dependency); ANTHROPIC_API_KEY
                                     #   from env/.env via python-dotenv; never imports decision/risk/strategies/backtest
scripts/
  run_paper_tick.bat              # Stage 8 ops: cd's into the repo, runs `arven paper run`, appends to
                                   #   data/paper/scheduled_run.log; invoked hourly by a Windows Scheduled Task
                                   #   ("ARVEN Paper Run", registered on the dev machine, not part of any commit)
tests/
  conftest.py               # make_config fixture (isolated tmp data_dir)
  synthetic_market.py, leakage_harness.py   # deterministic synthetic bars/funding/OI; generic truncation + perturbation checks
  bt_helpers.py, bt_scenarios.py            # Stage 4: tiny hand-made markets, scripted/random providers, the independent oracle engine,
                                             #   bulk_insert_1m/bulk_insert_funding (COPY-based; see "Operational notes")
  unit/                     # time, timeframes, types, config, binance_bulk, download, resample
                             #   test_binance_rest.py, test_rest_ingestion.py (Stage 8, offline fake REST opener)
                             #   test_macro_config.py (Stage 9a: DST offset hand-computed both directions, real-
                             #   calendar sort/dedup/coverage, hash determinism, no-actual-field guarantee)
  rest_helpers.py           # Stage 8: shared offline fake for Binance's public REST API (no sockets)
  integration/test_ingestion_pipeline.py   # local fake-Binance HTTP server: formats, resets, 404, checksum, rollback, idempotency, quality
  features/                 # indicators, series + as-of, bar features (warm-up, alignment, delay, gaps), funding/OI/time, config/registry/builder, cache
  backtest/                 # config/Signal/MarketData, costs/margin, hand-computed accounting (~30 cases), oracle (300 seeds), invariants,
                             #   baselines, metrics, report/determinism (golden hashes), splitguard+loaders, runs integration, static rules
  leakage/                  # test_no_lookahead (every feature), test_canary, test_static_rules, test_real_data (opt-in),
                             #   test_backtest_leakage.py (Stage 4: FeatureView/clock, prefix invariance, perturbation, cheater vs random)
                             #   test_ml_leakage.py (Stage 6: all 5 canary types - future label, future feature, shuffling,
                             #   full-period normalisation, sealed-test contamination)
                             #   test_wfo_leakage.py (Stage 7: static scan for BacktestPeriod.TEST/allow_sealed, fold-inside-test
                             #   returns None, direct TEST resolve still raises SealedAccessError, real schedule stays in dev+val)
                             #   test_paper_leakage.py (Stage 8: FORWARD never resolves/falls back to TEST, no backward reach)
                             #   test_macro_leakage.py (Stage 9a: the blackout decision is a pure function of (t, calendar)
                             #   with no data input to leak; the loader takes no market/decision-time parameter at all)
  stage5_helpers.py, pipeline_helpers.py    # Stage 5: exact-value FeatureView builder (real Stage 3 column names); synthetic-market-driven
                                             #   pipeline runner, truncate/garbage helpers for both the feature and 1m-market sides
  regime/, strategies/, decision/, risk/    # hand-computed unit tests per rule/branch, plus each package's own config-validation tests
                                             #   (risk/test_risk_engine.py gained 12 Stage 9a cases: the blackout
                                             #   window's boundary in both directions, which event wins, state still
                                             #   updates under a veto, NO_TRADE never reaches rule 2, empty-calendar no-op)
  pipeline/                 # test_pipeline_wiring, test_stage5_static_rules, test_leakage, test_determinism,
                             #   test_backtest_integration (accounting invariants via the real engine), test_pipeline_real_data (opt-in)
                             #   test_stage5_no_ml_regression.py (Stage 6: Stage5Pipeline with ml_filter=None is byte-identical)
  ml/                       # Stage 6: test_labels (hand-computed triple-barrier), test_splits (purge/embargo property test, 20 seeds),
                             #   test_model, test_calibration (PAVA), test_ml_metrics, test_dataset (regression vs a direct Stage5
                             #   replay), test_artifact (round trip, manifest completeness, hash verification/determinism), test_filter
                             #   (30-seed property test), test_ml_config, test_ml_static_rules (import boundaries), test_ml_real_data (opt-in)
  wfo/                      # Stage 7: test_wfo_schedule (the real 17-window schedule, minimum-windows gate, partial-window
                             #   flagging), test_wfo_causality (direct instrumentation + perturbation-invariance of causal
                             #   hyperparameter/calibration selection), test_wfo_determinism, test_wfo_fit (purge/embargo-minus-
                             #   calibration mask, degenerate-split handling, calibration-lookback capping), test_wfo_backtest
                             #   (window resolution incl. the real fold-10 check, regime-hysteresis reset across windows),
                             #   test_wfo_static_rules (import boundaries, no reimplementation of Stage 6 primitives)
  paper/                    # Stage 8: test_paper_runs (synthetic DB -> REST tail -> resample -> forward window ->
                             #   real Stage5Pipeline -> written artifact; the resample-range regression test),
                             #   test_paper_static_rules (import boundaries, no reimplementation of Backtester/Simulator)
  llm/test_anthropic_client.py    # Stage 9b: response parsing, retry on 5xx, no retry on 401/403, the
                                   #   no-silent-default missing-API-key guarantee - offline (scripted opener)
  news/                      # Stage 9b: test_rss (real-shaped RSS fixtures, missing-field/unparseable-date
                             #   skipping, timezone conversion), test_schema (valid/invalid LLM output,
                             #   markdown-fence tolerance), test_runs (fetch->store->structure end to end
                             #   against fakes, idempotency, cost-control cap, malformed-response recording),
                             #   test_news_config, test_news_static_rules (import boundaries, forward-only
                             #   by construction - never imports SplitGuard/BacktestPeriod)
  test_reports.py           # per-regime breakdown (hand-built fixtures)
```
Full suite: **1678 passed, 13 skipped** (`.venv/Scripts/python.exe -m pytest`, about 8 minutes), all passing.
Stage 9b adds 40 new tests (`tests/llm/`: 6, `tests/news/`: 34 across 5 files); no opt-in real-data test was
added since there has been no real Anthropic API call yet (see "Stage 9b" above for why).
Stage 9a adds 33 net new tests (21 in two new files — `tests/unit/test_macro_config.py`: 18,
`tests/leakage/test_macro_leakage.py`: 3 — plus 12 new cases added to the existing
`tests/risk/test_risk_engine.py`); no opt-in real-data test was added (the mechanism's only "real data" is
the committed `config/macro_events.csv`, already exercised directly by `test_macro_config.py`).
Stage 8 added 39 net new tests (32 in new files across `tests/unit/`, `tests/leakage/`, `tests/paper/`, plus a
net +7 in the existing `tests/backtest/test_splitguard_and_loading.py` for the new FORWARD period); the 13
skips are unchanged opt-in real-data checks — Stage 8 adds no new opt-in real-data test, since its real-data
run is exercised directly via `arven paper run` (documented in the "Stage 8" section above) rather than as a
pytest-collected check, the same choice Stage 7 made for `arven wfo run`.
Stage 7 added 36 tests (`tests/wfo/`: 32, `tests/leakage/test_wfo_leakage.py`: 4); the 13 skips are unchanged
opt-in real-data checks (7 from Stages 3-5 + 6 from Stage 6 — Stage 7 adds no new opt-in real-data test, since
its real-data run is exercised directly via `arven wfo run`, documented in the "Stage 7" section above, rather
than as a pytest-collected check). All 13 pass together:
`ARVEN_REAL_DATA_TESTS=1 .venv/Scripts/python.exe -m pytest tests/leakage/test_real_data.py
tests/pipeline/test_pipeline_real_data.py tests/ml/test_ml_real_data.py` (about 123 s; add
`ARVEN_REAL_DATA_SAMPLES=200` for the fuller Stage 3 sample count).

### Conventions (all later stages must follow)

**Bars and timestamps**
- Bars cover `[open_time, close_time)` with `close_time = open_time + duration`, aligned to the UTC epoch (valid for timeframes ≤ 4h).
- In DuckDB every time column is a **BIGINT UTC epoch-ms** with an `_ms` suffix.
- A bar is usable from `close_time_ms + data.bar_availability_delay_seconds`. This delay is applied when reading and is not stored.
- `core.timeframes.last_closed_bar_open(t, tf, delay)` returns the latest usable bar at `t`. Use it (or an equivalent as-of join) for every multi-timeframe lookup.

**Funding and OI**
- Funding: `funding_time_ms` is rounded to the whole hour, and the raw value is kept in `raw_funding_time_ms`. Ingestion fails if the drift exceeds 1 s. `available_at_ms = max(raw, normalised)`.
- OI (`open_interest`): `available_at_ms = ts_ms + data.open_interest_availability_delay_seconds`, default 300 s. This is a conservative choice because Binance's publication lag is unknown.
- Missing OI (before 2020-09-01, or days Binance lacks) = **no rows**. Never fill it with zeros or back-filled values. Stage 3 must turn it into NaN.

**Derived bars**
- `ohlcv` rows with `is_complete = false` exist when 1m minutes are missing. Consumers must exclude them or treat them explicitly.

**Config and periods**
- Periods in config are half-open `[start, end)`. A date without a time means 00:00 UTC; a datetime without an offset is rejected.
- Costs are in basis points per side (`cfg.costs.fees.fee_bps(order_type)`).
- `config_hash()` excludes `data_dir` and the `download` section. It is recorded in `ingestion_runs`.

**Ingestion contract** (a violation fails the whole file, rolled back)
- Every row must fall inside the file's period.
- Klines: `close_time` must equal `open + duration − 1ms`, and `open_time` must be aligned.
- Funding: drift must be ≤ 1 s.
- Metrics: the symbol must match.
- Duplicates: exact duplicate rows are dropped and counted in `source_files.duplicate_rows_dropped`. Duplicate keys with different values fail the file.

### How to run

```
.venv/Scripts/python.exe -m arven ingest     --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven resample   --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven crosscheck --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven quality    --start 2024-01-01 --end 2024-03-01
.venv/Scripts/python.exe -m arven export
.venv/Scripts/python.exe -m arven status
.venv/Scripts/python.exe -m arven features build     # full history -> data/features/v1/ (about 7 s, 282 MB peak; DB opened read-only)
.venv/Scripts/python.exe -m arven features check     # cache hash/invariants + development-period statistics only
.venv/Scripts/python.exe -m arven features status
.venv/Scripts/python.exe -m arven backtest run --provider no_trade|buy_and_hold|random_entry|pipeline --period development
.venv/Scripts/python.exe -m arven backtest baselines --period development   # no_trade + buy_and_hold + random_entry, side by side, no ranking
.venv/Scripts/python.exe -m arven backtest verify <run_id>                  # recompute hashes from the written files
.venv/Scripts/python.exe -m arven backtest show <run_id>
.venv/Scripts/python.exe -m arven wfo run                                   # Stage 7: full 17-window causal walk-forward schedule
.venv/Scripts/python.exe -m arven wfo show <run_id>                         # print a stored WFO report.json
```
`--provider pipeline` runs the full Stage 5 regime+strategies+decision+risk pipeline and additionally prints a
per-regime breakdown after the usual metrics.
`backtest run`/`baselines` take `--start`/`--end` (must lie inside `--period`, default the whole period),
`--stress` (multiplies slippage by `costs.slippage.stress_multiplier`), and, for the sealed `test` period only,
`--allow-sealed --reason "..."` (logged permanently before any data is read).
`wfo run` takes no arguments — it always covers the full development+validation range with both model families
and writes to `data/wfo/<run_id>/report.json`; it never touches the sealed test period (see "Stage 7" above).

The data examples above use the 2024-01 → 2024-03 slice. Without `--start`/`--end`, commands use
`data.history_start`/`history_end` (the full 2020-01 → 2026-07 period).

The full backfill is already completed and verified (see "Full backfill results"), so there is nothing left to
backfill. A full-period `ingest` re-run is idempotent: it skips all already-ingested files and downloads nothing
(verified in "Final verification"). Use `--start`/`--end` to limit a run to a sub-range. `crosscheck` has so far only
been run on sample months.

## Historical: Step-1 test-slice results (2024-01-01 → 2024-03-01, run 2026-09-28)

_These are the results of the small Step-1 test slice, kept for reference. They are **not** the final results; for
those see "Full backfill results" and "Final verification" above. The sizes and full-period estimate at the end of this
section are superseded by the actual full-backfill figures._

**Ingestion**
- 64 files: 2 monthly 1m klines, 2 monthly funding, 60 daily metrics.
- 64 downloaded, 64 ingested, 0 failed. About 2.5 minutes, mostly the 60 daily metrics requests.

**Row counts**

| Table | Rows |
|---|---|
| `ohlcv_1m` | 86 400 (= expected) |
| `ohlcv` 5m / 15m / 1h / 4h | 17 280 / 5 760 / 1 440 / 360 (0 incomplete) |
| `funding_rates` | 180 (= expected), 26 rows had 1–4 ms jitter |
| `open_interest` | 17 155 of 17 280 expected |
| `ohlcv_native` | 24 840, from 8 native files |

The missing OI rows are a **real source gap**: Binance's own `BTCUSDT-metrics-2024-02-16.zip` ends at 13:30. There are
125 missing snapshots from 2024-02-16 13:35 to 2024-02-17 00:00, recorded in `data_gaps`.

**Quality**
- 36 of 38 checks PASS. The 2 WARNINGs are the OI gap above.
- 0 errors.
- The source-consistency check re-read all 64 raw files: row counts and value sums match the DB.

**Cross-check against Binance native klines**
- 5m, 15m, 1h and 4h: 100% of bars present on both sides.
- 0 price mismatches, 0 trade-count mismatches.
- Maximum relative volume difference 3e-16 (1 ULP).

**Idempotency**
- A second `ingest` run skipped all 64 files in about 1 s, with no network.
- `ingest --refresh` re-verified the checksums online and re-ingested all 64 files.
- Content fingerprints of all tables were identical before and after both runs.

**Sizes**

| Item | Size |
|---|---|
| raw zips (incl. native cross-check files) | 5.4 MB |
| Parquet | 5.2 MB (ohlcv 4.58 MB, OI 0.80 MB) |
| DuckDB file | 30.4 MB (18.1 MB compacted) |

The DuckDB file is larger than the Parquet export because of primary-key ART indexes, 256 KB block granularity,
and space not reclaimed after the `--refresh` re-ingest.
- **Revised full-period estimate:** DuckDB ≈ 0.4–0.8 GB, Parquet ≈ 0.2 GB, raw ≈ 0.17 GB. This replaces the preflight's
  150–300 MB DuckDB guess.
- Options, not yet decided:
  - compact periodically with `COPY FROM DATABASE`
  - drop PK indexes on bulk tables and rely on the quality duplicate checks instead

## Preflight facts (2026-09-28)

**Connectivity**
- `data.binance.vision` and `fapi.binance.com` are reachable.
- About 10% of TCP connections get reset. The downloader handles this with retries.

**Bulk data**
- Monthly 1m klines and funding files exist for 2020-01 … 2026-08.
- Daily metrics start **2020-09-01**.
- Old kline CSVs have no header row.
- Funding timestamps carry ms jitter.
- Early metrics files contain exact duplicate rows (e.g. 2020-09-01 has every row twice).

**Full-period download:** 78 + 78 + 2 129 files ≈ 171 MB zipped. The daily metrics requests dominate the time: about 1 h
sequentially, based on this run's rate of roughly 2.3 s per file.

## Open issues / decisions for the user

1. ~~Full backfill~~: done. ~~Stage 3 features~~: done and approved. ~~Stage 4 backtester~~: done and approved
   (including the final `liquidation_includes_funding=true` decision, #13 below). ~~Stage 5 pipeline~~: done and
   approved, committed `2298e5a`. ~~Stage 6 ML meta-filter~~: done, approved and committed `e9b7c72`.
   ~~Stage 7 walk-forward evaluation (WFO)~~: done, approved and committed `aa43c1b`. Headline finding:
   **Stage 6's single-run +8.6% result does not replicate**; the baseline loses money in all 16 backtestable
   windows, and neither the logistic nor the LightGBM MetaFilter shows a replicated predictive edge (raw
   ROC-AUC 0.42–0.60 throughout). ~~Stage 8 paper-signal loop~~: done, approved and committed `f4f3787`. First
   forward result: baseline −14.9% over 94.4 days (consistent with every Stage 7 window), logistic MetaFilter
   flat at +0.06% on 2 trades (consistent with Stage 7's non-replication finding, not a new positive result).
   ~~Stage 9a macro calendar + risk blackout~~: done, approved and committed `b67afd0`. All 8 risk engine
   rules now exist. ~~Stage 9b news ingestion + LLM structuring~~: done, approved and committed `b9164d5`.
   News source is RSS, not CryptoPanic (its free API tier was discontinued in early 2026, found during
   design). **Stage 10 LLM explanations/Q&A + Streamlit dashboard**: implemented and unit-tested (30 new
   tests, full suite 1708 passed/13 skipped) — see "Stage 10" above; the dashboard itself was also
   smoke-tested against this machine's real local data. **Neither Stage 9b nor Stage 10's LLM calls have
   been validated against the real Anthropic API** (no key available in-session) and **neither is wired
   into any decision/risk logic** — all deliberate, acknowledged gaps, not oversights.
2. ~~`forward_start = 2026-07-01` is already in the past~~: **resolved by Stage 8** — it needed no relabelling.
   The gap between `history_end`/`forward_start` (2026-07-01) and the day Stage 8 actually ran (2026-10-03,
   ~94 days) was simply backfilled via the new REST-tail path (the same public endpoints, just incremental)
   before the first forward decision; `forward_start` itself stays exactly as originally configured, and the
   forward period's own definition (`[forward_start, now)`, growing) makes any future gap between runs
   self-healing the same way, by construction.
3. ~~Contiguous splits with no embargo~~: **resolved by Stage 6's purged, embargoed expanding-window
   walk-forward** (`src/arven/ml/splits.py` — 96-hour embargo, purges any training row whose label horizon
   overlaps a validation block; 20-seed exhaustive property test). The underlying Stage 4/5 chronological
   development/validation/test split dates are still contiguous with no embargo between them (unchanged,
   as instructed) — Stage 6 only adds embargo *within* its own walk-forward folds, on top of that.
4. **DuckDB size and compaction.** The DB is 475 MB uncompacted for the full period; the storage design is frozen for now.
5. ~~Stage 3 input decisions~~: resolved by the missing-data policy in "Stage 3 — features" (OI gaps and the pre-2020-09 boundary
   are NaN with staleness, never interpolated; zero-volume ratios are NaN; the 2021-05-15 anomaly is left as is).
6. LLM provider (later). Thesis success criterion.
7. **Top-trader and taker long/short ratios are empty in the source from 2021-12 to 2022-12 (taker: to 2022-05).** `oi_top_ls_log` /
   `oi_taker_ls_log` are therefore NaN for a large part of the development period. **None of the Stage 5 strategies or the
   regime detector read either column** (the regime stress flag uses `oi_chg_1h`, not the ratios), so Stage 5 did not need to
   resolve this. **Stage 6:** both columns are included in LightGBM's full 78-column feature set (they are among the 60
   causal Stage 3 columns) but excluded from logistic regression's 69-column set, since neither is Stage-3 `required=True`
   (D7 — the required/optional split, not an ad hoc Stage 6 selection). No NaN-imputation or dropping was added; a NaN
   value flows into LightGBM's native missing-value handling the same way it would in any other Stage 6 row.
8. ~~The feature cache covers the whole history, including validation and sealed-test rows~~: **enforced by Stage 4's
   `SplitGuard`/`AllowedWindow`** — every backtest data read (1m bars, funding, feature rows) is confined to one configured
   period; a range crossing a period boundary is refused; the sealed test period additionally needs `--allow-sealed` and a
   `--reason`, logged to `data/backtests/sealed_test_log.jsonl` before any data loads. Verified: a development run's reader
   never queries at or after 2023-07-01 (`test_loaders_return_only_rows_inside_the_window_and_log_the_ranges`).
   **Stage 6 extends this, not replaces it:** `arven.ml_runs.train_and_save` resolves only `DEVELOPMENT`/`VALIDATION`
   through the same `SplitGuard`, and never resolves `TEST` (verified by test and by a static scan for the literal
   `BacktestPeriod.TEST` in `ml_runs.py`); a Stage-6-specific sealed-test evaluation log (analogous to
   `sealed_test_log.jsonl`) does not exist yet because no Stage 6 code path reaches the test period at all — left for
   whichever later stage first evaluates a trained model against the sealed test.
9. **Warm-up costs the first 167 days** of the development period for `feat_ready` (`h4_ema_dist_200` needs 1 000 4h bars).
   Lowering `warmup_factor` or dropping the 4h EMA200 is possible via `config/features.yaml`, at the price of a new feature version.
10. ~~Feature cache manifest recorded the pre-commit git hash~~: resolved — rebuilt once after the Stage 3 commit; the content
    hash (`c06b09e7…`) was verified unchanged and the manifest now records `git_commit = 6ac57d47…`.
11. `features build` always rebuilds the full history (about 7 s); there is still no incremental update to Stage 3's
    persisted cache (not added by Stage 8 either — the paper loop builds its own forward-period features fresh in
    memory each tick instead, see "Stage 8" above, deliberately leaving the canonical cache untouched). If bars are
    re-ingested, rebuild: the manifest's `source_fingerprint` identifies the data a cache was built from.
12. **Stage 4 assumptions not verified against Binance's live schedule:** `maintenance_margin_rate` (0.4%, single flat tier,
    no tiered schedule), `qty_step_btc` (0.001), `min_notional_usdt` (100). All are in `config/backtest.yaml`, clearly labelled,
    and easy to correct once checked. They affect margin/liquidation levels and rejection thresholds, not the accounting logic.
13. ~~`liquidation_includes_funding` needs your confirmation~~ — **resolved, final decision (2026-09-29):
    `liquidation_includes_funding = true`.** `liquidation_includes_funding` (config/backtest.yaml) was added beyond
    the approved D11 model. The first real buy-and-hold run (held ~3.5 years) showed the plan's fixed-liquidation-price
    model lets a persistently-paying long drain the wallet **below zero** without ever being liquidated — no real
    exchange allows negative equity on an isolated position. With the confirmed setting, funding is debited from the
    position's isolated margin and the liquidation price moves with it, so equity can no longer go negative. The
    alternative (`false`: fixed liquidation price, funding never triggers it, matching D11 to the letter) remains
    implemented and tested for reference (`test_funding_can_liquidate_when_it_is_debited_from_the_margin`,
    `test_long_hold_through_persistent_positive_funding_is_liquidated_not_negative`) but is not the configured
    behaviour. `config/backtest.yaml` and `docs/architecture.md` §9 reflect this as final, not provisional.
14. ~~Stage 5's ML filter step (architecture §13 step 4)~~ — **resolved: implemented in Stage 6** as
    `arven.ml.filter.MetaFilter`, wired optionally into `Stage5Pipeline` (see "Stage 6" above). The macro-event
    blackout (risk rule 2) **remains genuinely absent, not stubbed** — the risk engine still has no calendar
    check; it is explicitly Stage 9 (renumbered 2026-10-01 — was Stage 8 before the Stage 7 WFO insertion).
15. **Stage 5's regime/strategy/risk parameters are architecture-derived defaults, not fitted or searched**
    (CLAUDE.md: "do not optimize parameters"). The real development-period result (−20.3% over 3.5 years, 111
    trades) is a measurement of the framework, not evidence the three unoptimized strategies have an edge —
    see "Stage 5" above for the per-regime breakdown.
16. **Stage 6's LightGBM calibration underperforms on this dataset (0.630 raw → 0.788 calibrated log-loss)** —
    reported honestly rather than tuned away; see "Stage 6" above for the traced cause (a single small,
    isotonic-overfit calibration bin) and the resulting 0-trade backtest for that model family. A fix (fewer
    bins, Platt fallback, more data) is a candidate for a later stage, not attempted here.
17. **Stage 6's A/B and control backtests are each a single run over one fixed development-period slice**, not
    a seeded distribution the way Stage 4's baselines are. The logistic MetaFilter's +8.6% result is reported
    as single-run, suggestive evidence against its own controls (shuffled-label, matched-rate random filter),
    not a validated edge — consistent with CLAUDE.md's rule against implying guaranteed profitability.

## What does NOT exist yet

- ~~Dashboard~~: implemented in Stage 10 (`src/arven/dashboard/`, `arven dashboard`) — see "Stage 10" above.
  (The paper-signal loop exists — Stage 8; the macro calendar + risk blackout, Stage 9a, and news ingestion
  + LLM structuring, Stage 9b, both exist too. Neither Stage 9b's nor Stage 10's LLM calls are yet validated
  against the real Anthropic API, and neither is wired into any decision/risk logic.)
- Deduplication/clustering of near-duplicate news stories across sources (architecture.md section 15's
  remaining "useful" LLM bullet not yet built — explanations and Q&A over stored data, the other two
  bullets, were implemented in Stage 10).
- `MarketSnapshot` as a separate class (its job is done by `core.series.MarketInputs.available_until` and
  `data.reader`), and the `feature_sets` DuckDB table (replaced by `manifest.json`).
- ~~REST incremental updates (only bulk files are supported so far)~~: implemented in Stage 8
  (`data/adapters/binance_rest.py`, `data/rest_ingestion.py` — klines and funding only, see "Stage 8" above).
- ~~The macro-event blackout (risk rule 2)~~: implemented in Stage 9a (`config/macro_events.csv`,
  `core/macro_config.py`, `risk/engine.py` rule 2) — see "Stage 9a" below. (The ML probability gate, decision
  step 4, exists since Stage 6.)
- A saved, dedicated Stage 7 WFO report format beyond the one `report.json` per run, and any dashboard/plot of
  per-window results over time — left for a follow-up (see "Stage 7" above).
- A 4th strategy (funding/positioning contrarian, architecture §13 item 4) — out of the explicit Stage 5 scope.
- A formalised, saved Stage 6 diagnostics report (SHAP summary, calibration reliability diagram, per-regime/
  per-strategy `P(success)` breakdown as a report artifact, mirroring `arven.reports.per_regime_breakdown`)
  and a reusable `arven ml` A/B-comparison subcommand — the underlying metrics/SHAP/comparison all run today,
  just via separate ad hoc invocations, not one saved artifact or command.
- A Stage-6-specific sealed-test evaluation log (`arven.ml_runs` never reaches the test period at all yet, so
  there is nothing to log — see open issue #8).
- Git: branch `feat/historical-data`; commits `efb6677` (Stage 1+2), `4be9329` (docs), `6ac57d4` (Stage 3),
  `8009719` (Stage 4), `a6da56b` (docs), `2298e5a` (Stage 5), `e9b7c72` (Stage 6), `aa43c1b` (Stage 7),
  `f4f3787` (Stage 8), `b67afd0` (Stage 9a), `b9164d5` (Stage 9b). Stage 10 (LLM explanations/Q&A +
  Streamlit dashboard) is included in this commit.

## Environment

- `.venv`: Python 3.13.12.
  - Added in Stage 1: `pyyaml`, `pytest`.
  - Added in Stage 2: `duckdb 1.5.5`, plus the project itself installed editable (`pip install -e .`).
  - Added in Stage 3: `numpy 2.5.3` (the only new dependency; the install needed several retries because of connection resets).
  - Stage 4 and Stage 5 added no new dependencies.
  - Added in Stage 6: `lightgbm 4.7.0` (pulled in `scipy 1.18.1`, `narwhals 2.26.0`); the install needed retries
    (`--retries 15 --timeout 60`) because of the same connection-reset behaviour seen with `numpy` in Stage 3.
  - Stage 7 added no new dependencies.
  - Stage 8 added no new dependencies: REST calls reuse `Downloader.fetch_bytes` (stdlib `urllib.request`),
    exactly as the bulk downloader already does.
  - Stage 9a added no new dependencies: considered `tzdata` (for `zoneinfo`) and deliberately did not add it —
    this machine's Python has no system IANA timezone database, and a fixed two-rule legal calendar (US DST)
    is cheap and correct to compute directly in stdlib instead (`core/macro_config.py`).
  - Added in Stage 9b: `python-dotenv` (for reading `ANTHROPIC_API_KEY` from `.env`) - already present in
    this venv as a "pre-existing package," now declared explicitly in `pyproject.toml`. No HTTP client
    library (the Anthropic Messages API is called via stdlib `urllib.request`, same choice as Stage 8's
    Binance REST client) and no RSS-parsing library (stdlib `xml.etree.ElementTree`).
  - Added in Stage 10: `pandas 3.0.6`, `streamlit 1.65.0` (pulled in `pyarrow 25.0.1`, `altair 6.3.0`,
    `pydeck 0.9.3`, and about 20 smaller packages: `pillow`, `protobuf`, `click`, `tornado`/`uvicorn`/
    `starlette`/`httptools`/`websockets`, `watchdog`, `jsonschema`, `requests`, `tzdata`, etc. - the full
    list is in `pyproject.toml`/the environment's own lockfile, not reproduced here). The install needed
    several long retries over a very slow connection on this machine (same connection-reset pattern already
    seen for `numpy` in Stage 3 and `lightgbm` in Stage 6, here manifesting as very slow trickling rather
    than outright resets); most packages were already downloaded from earlier partial attempts by the time
    the final, successful attempt completed in well under a minute.
- Pre-existing packages from the user: `openai`, `pydantic`, `httpx2`, `python-dotenv`.

## Decisions log

| Date | Decision | Status |
|---|---|---|
| 2026-09-28 | Point-in-time `available_at` on all data; as-of joins only | approved |
| 2026-09-28 | Store 1m bars as canonical; derive higher TFs; resolve SL/TP intrabar on 1m | approved |
| 2026-09-28 | DuckDB + Parquet for research/backtesting; no PostgreSQL for now | approved |
| 2026-09-28 | Decision TF 1h, context 4h, 5m/15m as features | approved |
| 2026-09-28 | Target historical period 2020-01-01 → 2026-07-01 (`data.history_end`) | approved |
| 2026-09-28 | ML as meta-labelling filter (triple-barrier), LightGBM + logistic baseline, purged walk-forward | approved (target) |
| 2026-09-28 | Rule-based regime detection first; HMM later as comparison | approved (target) |
| 2026-09-28 | Risk engine can only reduce/veto; default action NO_TRADE | approved (target) |
| 2026-09-28 | LLM only for news structuring, explanations, chat — after the quantitative core works | approved (target) |
| 2026-09-28 | Bar convention `[open, open+duration)`; costs in bps per side in config; strict frozen config with hash | implemented (Stage 1) |
| 2026-09-28 | Times stored as BIGINT epoch ms; bar availability applied on read; funding/OI store `available_at_ms` | implemented (Stage 2) |
| 2026-09-28 | DuckDB = source of truth, Parquet = fully rewritten export; raw zips kept immutable under `data/raw/<bucket key>` | implemented (Stage 2) |
| 2026-09-28 | Exact duplicate source rows dropped and counted; conflicting duplicates fail the file | implemented (Stage 2) |
| 2026-09-28 | OI availability delay 300 s (conservative, configurable) | implemented (Stage 2) |
| 2026-09-28 | Only new dependency is `duckdb` (stdlib for HTTP/zip/hash); no pandas/pyarrow yet | implemented (Stage 2) |
| 2026-09-28 | Stage 3 plan: numpy only; 1h bar-close decision grid; 5x configurable warm-up for recursive indicators; Parquet + manifest cache; v1 feature set; regime/strategy features left to Stage 5 | approved |
| 2026-09-28 | Features are pure numpy under `features/`; DB reading (`data/reader.py`) and cache I/O (`data/storage/feature_store.py`) live in `data/`; shared columnar types in `core/series.py` | implemented (Stage 3) |
| 2026-09-28 | Builds always start at the first stored bar (recursive indicators are seeded there); the cache is the canonical form | implemented (Stage 3) |
| 2026-09-28 | Missing data is NaN, never interpolated or carried forward; OI/funding staleness limits in `config/features.yaml` | implemented (Stage 3) |
| 2026-09-28 | Feature config has its own hash; `AppConfig.config_hash()` unchanged | implemented (Stage 3) |
| 2026-09-28 | Stage 4 plan: D1-D27 decision register (initial equity 10 000, leverage 3x, isolated margin, latency 0, run registry as files not a DuckDB table, ...) | approved |
| 2026-09-28 | Backtester implemented: SimulationClock, 1m Simulator, accounting equations, SplitGuard-enforced periods, hash-verified run artifacts, 3 baselines | implemented (Stage 4) |
| 2026-09-29 | `liquidation_includes_funding = true`: funding debited from isolated margin, so equity can never go negative (the D11 fixed-price alternative remains implemented for reference, not used) | approved (final) |
| 2026-09-29 | Stage 5 scope: rule-based regime (trend x vol + stress flag), 3 strategies (trend/momentum, breakout, mean-reversion — the 4th, funding contrarian, excluded), decision engine (regime gate + weighted vote, no ML filter), risk engine (8 ordered rules, no macro blackout) | approved |
| 2026-09-29 | Regime/strategy/risk gating and reporting kept in 4 separate packages (`regime`, `strategies`, `decision`, `risk`) plus `reports.py` outside `decision` for post-hoc analysis; boundaries enforced by static AST tests | implemented (Stage 5) |
| 2026-09-29 | No ML, no parameter optimization, no bypass of the Stage 4 engine — Stage 5 talks to Stage 4 only via `SignalProvider`/`Signal` | implemented (Stage 5) |
| 2026-09-29 | Stage 5 review approved, committed `2298e5a` | approved (final) |
| 2026-09-29 | Stage 6 D1: add LightGBM as the new dependency | approved |
| 2026-09-29 | Stage 6 D2: `MetaFilter` sits after `DecisionEngine.decide()` and before `RiskEngine.apply()`, resolving the architecture's diagram-vs-steps ambiguity in favour of operating on the single consolidated candidate | approved |
| 2026-09-29 | Stage 6 D3: dataset eligibility ignores portfolio-state risk rules only (position-open/daily-loss/drawdown/cooldown); all other risk rules still apply | approved |
| 2026-09-29 | Stage 6 D4: `retrain_interval_months=3`, `embargo_hours=96`, `min_train_months=12` | approved |
| 2026-09-29 | Stage 6 D5: fixed hyperparameter grid, ≤4 configurations per model family, no open-ended search | approved |
| 2026-09-29 | Stage 6 D6: isotonic calibration, fitted per walk-forward fold on held-out rows | approved |
| 2026-09-29 | Stage 6 D7: LightGBM uses all 60 causal Stage 3 columns; logistic regression uses only the 51 `required=True` Stage 3 columns (both + all 18 Stage 5 context columns) | approved |
| 2026-09-29 | Stage 6 implemented: labels, dataset construction (real regime/strategies/decision/risk replay), purged/embargoed walk-forward, numpy logistic regression + LightGBM, isotonic calibration, model artifacts with full provenance, `MetaFilter`/`RandomFilter`, CLI, 1523 tests incl. 5 leakage-canary types and determinism; real development+validation data: 7572/7196 eligible, logistic model +8.6% vs −20.3% baseline with shuffled-label and matched-rate-random controls (single run, not a validated edge) | implemented (Stage 6), approved, committed `e9b7c72` |
| 2026-10-01 | Roadmap renumbered to insert Stage 7 (walk-forward evaluation, WFO) between the ML meta-filter and the paper-signal loop; the former Stage 7 "Paper-signal loop" and everything after it shift to Stage 8-11 unchanged in scope | approved |
| 2026-10-01 | Stage 7 design: reuse Stage 6's `generate_folds` schedule unchanged (no separate Stage 7 calendar); hyperparameter selection for window `N` restricted to `folds[:N]`; calibration/threshold selection restricted to the union of the last 4 folds strictly before `N`; fold 10 (the one dev/validation-boundary-crossing window) excluded from backtesting only, kept in the schedule | approved (implemented) |
| 2026-10-01 | Stage 7's own pre-commit audit found and fixed a causal-leakage bug in its first implementation (hyperparameters/calibration had been selected using all folds, including the window under evaluation) before any real-data run or commit | implemented (Stage 7) |
| 2026-10-01 | Stage 7 real walk-forward result: Stage-5-only baseline negative in all 16 backtestable windows (mean total_return −11.2%); neither logistic nor LightGBM MetaFilter showed a replicated predictive edge (mean total_return ≈0%, raw ROC-AUC 0.42-0.60 in every window) — Stage 6's single-run +8.6% result does not replicate under genuine walk-forward evaluation | implemented (Stage 7), approved (final) |
| 2026-10-01 | Stage 7 review approved, committed `aa43c1b` | approved (final) |
| 2026-10-03 | Stage 8 design: add `BacktestPeriod.FORWARD` (implements `architecture.md`'s own "Data periods" table, not a new decision) rather than inventing a parallel paper-trading data path; the live loop computes "now" itself (one wall-clock read per tick) and is the only new thing that ever does; the real `Backtester`/`Stage5Pipeline` is reused unmodified via `runs.execute_run`, never a bespoke paper-trade tracker | approved (implemented) |
| 2026-10-03 | Stage 8 D2: REST-tail scope is klines + funding only; open interest and the top-trader/taker long-short ratios are not live-updated (optional, NaN-tolerant feature group already) | approved |
| 2026-10-03 | Stage 8 found and fixed two real bugs before trusting its first real run: (1) `con.executemany` into the PK-indexed `ohlcv_1m`/`funding_rates` tables measured ~33s per 1000-row REST page (fixed with the same staged-bulk-load idiom `ingestion.py` already uses, ~740x speedup); (2) a fixed 2-day resample lookback silently left most of a large REST catch-up's derived bars unbuilt, producing a false "0 trades over 94 days" result that was investigated rather than accepted, and fixed with a regression test | implemented (Stage 8) |
| 2026-10-03 | Stage 8 real forward run (live Binance data, forward_start=2026-07-01, 94.4 days): Stage-5-only baseline −14.9% (consistent with every Stage 7 historical window); logistic MetaFilter flat at +0.06% on 2 trades (consistent with Stage 7's non-replication finding) — the project's first genuinely forward, out-of-sample data point | implemented (Stage 8), approved (final) |
| 2026-10-05 | Stage 8 review approved, committed `f4f3787` | approved (final) |
| 2026-10-05 | Stage 9a scope (D1-D4): macro calendar covers FOMC/CPI/NFP only, sourced from official federalreserve.gov/bls.gov calendars (no scraping, no paid API); blackout window is symmetric and configurable (`macro_blackout_window_hours`, default 1.0h); rule 2 sits right after rule 1 (data-quality gate), before rule 7's portfolio-state checks; veto-only (no "reduce" variant) | approved |
| 2026-10-05 | `RiskEngine`/`Stage5Pipeline` gain one new `macro_events: tuple[MacroEvent, ...] = ()` constructor parameter, additive and byte-identical-when-absent (the same pattern Stage 6 used for `ml_filter`) - every previously-committed result (Stages 5-7, Stage 8's already-run paper ticks) stays exactly reproducible; `wfo_runs.py` deliberately left unchanged (still passes no macro_events) | approved (implemented) |
| 2026-10-05 | ET->UTC conversion for the calendar is computed from the fixed US DST rule directly (2nd Sunday of March .. 1st Sunday of November) rather than via `zoneinfo`, after discovering this Windows machine has no system IANA timezone database and the `tzdata` PyPI package would be a new dependency for a problem with exactly two fixed legal rules | implemented (Stage 9a) |
| 2026-10-05 | `config/macro_events.csv` compiled from real sources (228 rows, 2020-01..2027-12): FOMC dates from federalreserve.gov's own calendar page (incl. the real March 2020 emergency actions); CPI/NFP dates from bls.gov's archived news-release pages and schedule-of-releases pages (incl. the real 2025 government-shutdown reschedules and the one genuinely cancelled October-2025-reference-month release) | implemented (Stage 9a) |
| 2026-10-05 | Stage 9a review approved; full suite 1638 passed/13 skipped, no regressions in Stages 1-8 | approved (final) |
| 2026-10-05 | Stage 9a review approved, committed `b67afd0` | approved (final) |
| 2026-10-05 | News source corrected mid-design from CryptoPanic (chosen first) to free RSS feeds (CoinDesk, CoinTelegraph), after discovering CryptoPanic discontinued its free API tier in early 2026 (cheapest paid plan $50/week) - reported back before building anything against the paid API | approved |
| 2026-10-05 | LLM provider: Anthropic (`claude-haiku-4-5-20251001`), called via a thin stdlib-HTTP client rather than the official SDK - no new dependency, same choice already made for Binance REST in Stage 8 | approved |
| 2026-10-05 | Stage 9b design: forward-only by construction (no `BacktestPeriod` concept anywhere in the `news` package, rather than a date check) satisfies architecture.md's rule 11 (LLM training-cutoff contamination); the LLM only ever structures a headline into the fixed `NewsEvent` schema (`extra="forbid"`), never a trading decision; `max_items_per_tick` hard-caps LLM calls per tick for cost control; not wired into any feature/risk/decision - a separate, later integration decision | approved (implemented) |
| 2026-10-05 | Stage 9b implemented and unit-tested against fakes only (40 new tests); user chose to proceed without a real Anthropic API smoke test for now (no API key provided in-session) - acknowledged, documented gap, not a silent omission | approved (final) |
| 2026-10-05 | Stage 9b review approved, committed `b9164d5` | approved (final) |
| 2026-10-06 | User directive: finish the whole project's functionality and build an interface to see real reports/signals before returning to new-strategy experimentation - interpreted as Stage 10 (explanations/Q&A, per the roadmap's own stated deliverables) plus the Streamlit dashboard deferred since Stage 8 (A9) | approved |
| 2026-10-06 | Stage 10 design: `reports.decision_summary()`/`paper.runs._write_decision_history()` persist one `decisions.jsonl` per paper run as the fixed, already-computed payload explain/Q&A read from; `explain_decision` is never given the chance to suggest a different action (the decision already happened); `answer_question` answers only from a context block of already-stored artifacts and is told to say so when that context doesn't cover a question - a weaker, explicitly-documented guarantee than the rest of the project's point-in-time rules, since there is no structural schema gate on the output; `config/explain.yaml` uses `claude-sonnet-5-5` (more capable than Stage 9b's Haiku, since this is low-volume/user-triggered); the dashboard (`src/arven/dashboard/`) is a read-only presentation layer exempt from the stage-separation rules, calling the LLM only on an explicit button press, never on page load | approved (implemented) |
| 2026-10-06 | Found and fixed a real bug while testing `llm.context.load_recent_news` against a fresh config with no database file yet: an unhandled `duckdb.IOException` on the very first `arven ask` before any run had created the DB file - fixed to return `[]` (missing data stays safe and empty, never a crash) | implemented (Stage 10) |
| 2026-10-07 | `pip install streamlit` needed several long retries over a very slow connection (10MB in 10 minutes on the first attempt; a background-process memory-pressure guard also killed one attempt mid-install after the downloads had already finished) - the user explicitly approved each retry rather than the install being silently retried | approved |
| 2026-10-07 | Stage 10 implemented and validated: 30 new tests (full suite 1708 passed/13 skipped); the dashboard was additionally smoke-tested against this machine's real local data (16 paper runs, 20 backtest runs) via both a headless `streamlit run` and a direct `runpy` execution of its own logic, both clean; a `use_container_width` deprecation (already past its removal date in the installed streamlit 1.65.0) was found and fixed before commit | implemented (Stage 10), approved (final) |
| 2026-10-07 | Owner authored and committed `docs/ARVEN_MASTER_PROMPT.md` (`b9b28e8`): a larger, separate signal-product initiative (event-driven engine, new strategy, Telegram, web app), with its own honesty contract, strategy-grading gate, and 12-phase plan - explicitly additive to, never replacing, the thesis-core Stages 0-10 and their golden `result_hash` | approved |
| 2026-10-07 | Master-prompt Phase 0 (safety net): tag `pre-signal-product` on the master-prompt commit; new branch `feat/signal-product`; golden regression and `result_hash 3eca0a70...` reconfirmed; full-suite baseline recorded at 1708 passed/13 skipped (matches the master prompt's own stated baseline exactly) | approved (implemented) |
| 2026-10-07 | Master-prompt Phase 1 design: `StrategySpec`/`BarCloseEvent`/`EventClock` live in a new, isolated `arven.engine` package (imports only `arven.core`, never the legacy decision/risk/strategies/regime/backtest stack, enforced by a static test) rather than extending any existing module - the legacy 1h-only `Clock`/`FeatureView`/`Stage5Pipeline` path is untouched; tie rule for events sharing one `close_ms` is coarsest-timeframe-first, chosen so a strategy's `trigger_tf` event is always ordered after any coarser same-instant context close, removing a class of look-ahead bugs by construction | approved (implemented) |
| 2026-10-07 | Master-prompt Phase 1 implemented and validated: 32 new tests (`tests/engine/`), full suite 1740 passed/13 skipped, no regressions | implemented (Phase 1), approved (final) |
| 2026-10-07 | Master-prompt Phase 2 design: one generic `compute_tf_features` (same code for every timeframe; regularized grid + the shared `features/indicators.py` primitives; minimal set close/ATR/ATR%/EMA20-50 distance/EMA50 slope/ADX, names qualified as `"<tf>.<name>"` so they cannot collide with Stage 3) in new files under `arven.engine`, neither reusing nor touching the frozen Stage 3 `bars.py`/`builder.py`; `MultiTFView` returns the last row with `available_at <= t` per timeframe, raises the engine's own `LookAheadError` only when no such row exists at all, returns stale rows (older than one bar) as all-NaN like the Stage 3 builder's `max_age`, and treats warm-up/gap NaNs as defined readings (never raises) | approved (implemented) |
| 2026-10-07 | Master-prompt Phase 2 implemented and validated: 146 new tests (`tests/engine/`); truncation + perturbation leakage gate passes for every new feature column and for `MultiTFView` (incl. delay, gappy/stale data, event-driven, and a leaky-view canary); full suite 1886 passed/13 skipped, no regressions | implemented (Phase 2) |
| 2026-10-07 | Master-prompt Phase 3 design: the event-driven backtest loop (`EventBacktester`) lives in `arven.backtest.event_engine` and imports *from* `arven.engine` (clock/events only), so the Phase 1/2 rule "`arven.engine` never imports `arven.backtest`" holds verbatim; it reuses the Stage 4 `Simulator` unchanged with exactly the legacy call sequence, returns the legacy `BacktestResult`, never imports `Backtester` or `arven.backtest.clock`, and no legacy module imports it (new static test) | approved (implemented) |
| 2026-10-07 | Phase 3 loop semantics: providers keyed by trigger timeframe, decide only on their own timeframe's events; events of unregistered timeframes skipped entirely (no simulator call); same-instant dispatch follows the Phase 1 coarsest-first rule; one account / one net position (a second entry is rejected `position_open`); strict clock validation (monotonic, inside the window, exactly the window's decision times per registered timeframe) - a naively-built `SimulatedEventClock(start, end)`, which is shifted one bar late, is refused, and `WindowEventClock` builds the correct window clock | approved (implemented) |
| 2026-10-07 | Master-prompt Phase 3 implemented and validated: identical `result_hash` (table by table) between legacy `Backtester` and `EventBacktester` with an H1-only clock for the real `Stage5Pipeline` on seeds 0/5/9/17/22 (all with real trades) under real, zero and 2x-stress costs, plus scripted all-branches and all-`None` runs; 48 new tests (+2 auto-parametrised), full suite 1936 passed/13 skipped, no regressions | implemented (Phase 3) |
| 2026-10-08 | Master-prompt Phase 4 design: `EngineSignal`/`TPLevel`/`SignalUpdate`/`Grade`/`TrackRecord`/`resolve_legs` (pure types, `arven.engine`) are additive to `core.signal.Signal`, never replacing or feeding back into it; `resolve_legs`'s R-multiple convention mirrors `arven.backtest.accounting` exactly (`risk = |entry-stop|`, `r_multiple = net/risk`, generalised to many legs); `paper_tracker.py` lives in `arven.backtest` (not `arven.engine`), the same `backtest -> engine` dependency direction Phase 3 established, so it can reuse `backtest.costs` directly; funding is deliberately not modelled in the paper tracker (documented scope cut, not an oversight) | approved (implemented) |
| 2026-10-08 | Phase 4 intrabar rule for the TP ladder: a stop always beats a take-profit in the same bar (mirrors `execution.py`'s documented rule exactly); at most one rung resolves per bar even if a bar's range technically reaches two at once - the same "assume the worse/slower outcome when the 1m data can't distinguish order" spirit as CLAUDE.md rule 4 | approved (implemented) |
| 2026-10-08 | Corrected a Phase 3 test rather than weakening it: `test_event_engine_static_rules.py`'s "legacy backtest modules never import the engine" check had hard-coded an exclusion for only `event_engine.py`; extended to also exclude the new, equally legitimate `paper_tracker.py`, while still forbidding every other `arven.backtest` file from importing either | implemented (Phase 4) |
| 2026-10-08 | Master-prompt Phase 4 implemented and validated: 78 new tests across `engine/signal.py`, `signal_events.py`, `grading.py`, `ladder.py`, `signal_store.py` and `backtest/paper_tracker.py` (incl. hand-computed R-multiple and TP-ladder cases, the same-bar stop-beats-TP tie rule, one-rung-per-bar, break-even-stop, time-stop, and a tampered-signal-store rejection); full suite 2014 passed/13 skipped, no regressions, golden regression green | implemented (Phase 4), approved (final) |
| 2026-10-08 | Master-prompt Phase 5 design: the always-on loop wraps the existing, unmodified `run_paper_tick` (no new decision/execution logic) rather than re-deriving REST-tail/resample/decide; the one genuinely new piece of logic - skip a tick when `latest_forward_window_end_ms` has not advanced - is necessary, not optional, since `run_paper_tick` writes a new artifact on every call with no short-circuit of its own; no second persisted cursor is added since `run_paper_tick` is already fully self-resuming; graceful shutdown is cooperative (`KeyboardInterrupt` + a `--stop-file` sentinel), not signal-based, because Windows' asyncio loop does not support POSIX signal handlers | approved (implemented) |
| 2026-10-08 | `LiveEventClock` (the live `EventClock` implementation deferred since Phase 1) is built now for architectural symmetry but deliberately not yet wired into the real paper loop - that wiring waits for a genuine multi-timeframe strategy to need it (Phase 7), the same discipline already applied to `MultiTFView` | approved (implemented) |
| 2026-10-08 | A pre-existing Phase 2 leakage-idiom regex test false-positived on the prose word "backfill" in a new `LiveEventClock` docstring (describing legitimate real-time catch-up, not a leakage pattern); fixed by rewording the docstring rather than weakening the still-valid check | implemented (Phase 5) |
| 2026-10-08 | Master-prompt Phase 5 code implemented and validated offline: 23 new tests (`engine/clock.py`'s `LiveEventClock`, `paper/runtime.py`'s polling loop/heartbeat/structured log, all against fakes/injectable clocks, no real sleep or network); full suite 2037 passed/13 skipped, no regressions, golden regression green. **The phase's own gate - a 48-hour soak on live public data - was deliberately not run**: a real-time, multi-day, unattended network process against a laptop that must stay powered is a resource commitment requiring the owner's own go-ahead, not something to start unilaterally; `docs/RUNTIME_OPERATIONS.md` has the Task Scheduler/power-settings recipe ready for whenever that is decided | implemented (Phase 5), soak test pending owner decision |
| 2026-10-08 | Owner's explicit choice when asked: skip the Phase 5 48h soak test for now and move on to Phase 6 (Telegram) rather than run it unattended first - the soak remains a documented, ready-to-run gap (`docs/RUNTIME_OPERATIONS.md`), not silently dropped | approved |
| 2026-10-08 | Master-prompt Phase 6 design: `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_IDS` are both secrets (env/`.env` only, never YAML), mirroring `ANTHROPIC_API_KEY`'s own precedent; the outbox's primary key itself (`sha256(signal_id, event_type, chat_id)`) is the idempotent-send dedupe, not a separate check; `/pause`/`/resume` only mute a chat's own notifications (`telegram_chat_state`), never touch the trading loop; message text is pure formatting of already-computed `EngineSignal`/heartbeat/signal-store data (CLAUDE.md rule 9) | approved (implemented) |
| 2026-10-08 | A real bug found while hand-smoke-testing the new CLI (not by the unit tests): `arven telegram commands` crashed with a raw traceback when `TELEGRAM_BOT_TOKEN` was unset, because `run_telegram_commands_tick`'s `get_updates` call - unlike every entry in `run_telegram_send_tick`'s own loop - was not wrapped in a try/except; `arven telegram send` only avoided the same crash because its default `dry_run: true` short-circuits first. Fixed at the source, with a regression test, not papered over at the CLI layer | implemented (Phase 6) |
| 2026-10-08 | A second, self-inflicted static-test false positive (the "no order/account endpoint" check for `telegram/client.py` also forbade the substring "binance", copied carelessly from an unrelated check, and tripped on the client's own accurate docstring prose) was fixed by dropping the irrelevant word from the check | implemented (Phase 6) |
| 2026-10-08 | Master-prompt Phase 6 implemented and validated offline: 56 new tests (`tests/telegram/`: client retry/429/auth, outbox dedupe/failure-cap, message formatting, commands incl. real heartbeat/signal-store wiring, both composition roots end-to-end against a scripted fake Bot API); full suite 2093 passed/13 skipped, no regressions, golden regression green. **The phase's "owner supplies token for a live test" step has not happened** - no real `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_IDS` provided in any session so far; `arven telegram test` is ready to confirm it once they are | implemented (Phase 6), live test pending owner |
| 2026-10-08 | Master-prompt Phase 7 split into 7a/7b (the same precedent as Stage 9a/9b): 7a is the formal spec (`docs/strategy_impulse_retest.md`, written before any code) plus the causal swing/impulse/zone/trendline/trigger/target detection math, hand-tested in isolation; 7b (wiring into a real `SignalProvider`/`EngineSignal`, the development backtest, windowed robustness, baselines, stress, per-regime-like breakdown, forward paper) is the deliberate next step, not started in this pass | approved |
| 2026-10-08 | S4 spec decisions: every threshold pre-registered before any evaluation (swing lag K=2, impulse >=3x ATR14, base candle >=1x ATR14, stop buffer 0.25x ATR14, Fib zone 0.5-0.618 per the master prompt's own text, extensions 1.0/1.414/1.618 with 50/30/20% close fractions); the master prompt's own underspecified "context 4h" role was made concrete (direction must agree with 4h `ema_slope_50`'s sign, reusing Phase 2's own feature via one `MultiTFView` row lookup) rather than invented ad hoc during implementation | approved (implemented) |
| 2026-10-08 | S4 evaluation methodology decision (spec §10): the backtest/WFO/baselines/stress evaluation in 7b will use S4's nearest target (TP1) and its stop only, through the unchanged Stage 4 execution model - the full TP ladder is evaluated on the forward/paper leg via the Phase 4 `paper_tracker` instead, so no change to the shared execution layer is needed for this strategy | approved |
| 2026-10-08 | A real sign-error bug was found by S4's own hand-computed tests before any other code used it: `build_decision`'s R-multiple formula applied `side` once instead of letting it cancel (`side**2 == 1`), giving a negative R for a short's profit target; the long-side test alone could not have caught this (`side=1` hid it) - fixed, with the short-side case as its own dedicated test | implemented (Phase 7a) |
| 2026-10-08 | Master-prompt Phase 7a implemented and validated: 27 new tests (`tests/engine/test_strategy_s4.py`, incl. a dedicated truncation/leakage test for `confirmed_swings` per CLAUDE.md's "mandatory for every feature" rule); full suite 2120 passed/13 skipped, no regressions, golden regression green | implemented (Phase 7a), approved (final) |
| 2026-10-08 | Phase 7b split into two parts (same precedent as 9a/9b, 7a/7b): part 1 is the `SignalProvider` adapter wiring S4 into a real, hand-verified end-to-end scenario; part 2 (the actual backtest/WFO/baselines/stress/per-regime/forward-paper evaluation) is deliberately deferred to its own step | approved |
| 2026-10-08 | A genuine cross-timeframe bug found while wiring S4 (not by Phase 7a's own unit tests, which never crossed a timeframe boundary): `TrendLine`/`find_trigger` treated bar indices as if they were time, correct only by accident within one timeframe's own array - a setup_tf-built trendline evaluated against trigger_tf bars exposed this immediately. Fixed by carrying real epoch-ms times throughout, with a dedicated regression test proving the old approach would evaluate the trendline at the wrong real time | implemented (Phase 7b) |
| 2026-10-08 | A real methodology flaw found empirically (not by unit tests, which had used hand-picked numbers that happened to overlap): spec §4's original "base candle = start_swing_index - 1" definition almost never overlaps the Fibonacci 0.5-0.618 band, which sits 38-50% up the impulse from its origin. Corrected (spec §4 revision, §11 variant log) to search for a qualifying base candle within the impulse leg itself, nearest the end first - matching how a real impulsive move often pauses partway through | implemented (Phase 7b) |
| 2026-10-08 | A pre-existing, Stage-4-era static rule (`arven.backtest` never imports `arven.features`) caught the provider's own ATR computation; resolved by moving ATR computation into `engine.strategy_s4.setup_tf_atr` (`arven.engine` may import `arven.features`, Phase 2's own precedent) rather than loosening the backtest package's long-standing boundary; the Phase 3/4 `backtest -> engine` static-rule pattern was extended a third time for `strategy_s4_provider.py` | implemented (Phase 7b) |
| 2026-10-08 | Phase 7b part 1 implemented and validated: 9 new provider tests + 5 static-boundary tests + 2 corrected Phase 7a tests; full suite 2139 passed/13 skipped, no regressions, golden regression green | implemented (Phase 7b part 1), approved (final) |
| 2026-10-09 | First real S4 development run exposed an O(n^2) wall-clock bug (Python-loop ATR/swings recomputed every 15m tick); fixed by vectorising `confirmed_swings` and caching the 1h setup side per 1h bar, with a cache-equivalence test | implemented (Phase 7b part 2) |
| 2026-10-09 | S4 v1.1 on development: 108 trades, win rate 14.8 %, -20.5 % (stress -27.3 %), max DD 38.3 %; gross +878 USDT turned negative by 2 758 USDT of fees+slippage; no implementation error found in hand audit; no tuning on this period; S4 stays EXPERIMENTAL; windowed robustness/forward paper/grade deferred | recorded (Phase 7b part 2), honest negative result |
| 2026-10-09 | Unchanged S4 v1.1 run on validation (+0.73 %, 40 trades, 17.5 % win rate, max DD 19.7 %) and forward (4 trades, +0.46 %); sealed test deliberately not run (needs explicit owner go, would be spent for later S4 variants); S4 stays EXPERIMENTAL | recorded (Phase 7b part 2b) |
| 2026-10-09 | Owner trades BTCUSD CFD on JustMarkets MT5: added `config/costs_cfd_justmarkets.yaml` (~2.5 bps round-trip spread, swap-free; unverified on owner's terminal) beside the untouched perp profile; pre-registered exit variants V0/A/B/C/D, `track_signal` gained `breakeven_at_r`; selection rule picked V0 (exits unchanged); breakeven worsened results; V0 under CFD costs +7.7 % dev / +18.3 % val but ~0 under spread stress; sealed test untouched | recorded (Phase 7b part 2c) |
| 2026-10-09 | Owner asked for more strategies in order S5 -> S6 -> S7 -> ML filter; S5 Squeeze-Breakout specified first (fixed parameters), implemented and evaluated once on development/validation: development -42 % (CFD -26 %), validation -8.1 % (CFD +1.4 %); no tuning, EXPERIMENTAL; S6 awaits the owner's go | recorded (S5) |
| 2026-10-09 | S6 Trend-Pullback specified (fixed parameters), implemented and evaluated once: development -22.6 % engine / +5.7 % CFD costs, validation -13.5 % / +4.1 %; 1.9-2.7 signals per week; edge ~+0.025 R per trade, inside noise; no tuning; EXPERIMENTAL; S7 and the ML filter await the owner's go | recorded (S6) |
| 2026-10-09 | ML signal filter for S4/S5/S6 pre-registered (logistic, walk-forward on development, one frozen validation test vs random-rejection control) and run once: dev OOF ROC-AUC 0.57, validation 0.62, kept mean R +0.095 vs +0.074 all, random 95th pct +0.198 -> NO VALUE, not adopted; sealed test untouched | recorded (ML filter) |
| 2026-10-10 | Pattern study of S4/S5/S6 outcomes (development mined with family-wise permutation control; nothing significant) and two rules fixed in advance (R1 no weak trend/no weekend, R2 calm market) both FAILED on validation; descriptive probe: signals confirmed by another strategy within 4 h did better in both periods (hypothesis for forward data); `docs/proposal_unified_strategy.md` written as information only (regime router + agreement grade), no code changed; all further evaluation uses broker (CFD) costs | recorded (pattern study + unified proposal) |
| 2026-10-10 | Forward evaluation of S4/S5/S6 wired as `arven paper strategies` (CFD costs, signal store, summary; not scheduled, no Telegram token yet); first 14 forward weeks: S4 -0.13 R (7), S5 -0.34 R (31), S6 -0.11 R (160); the agreement hypothesis is not supported (-0.33 R vs -0.09 R) | recorded (forward wiring) |
| 2026-10-10 | Phase 8 split into 8a (API) / 8b (React app) / 8c (browser tests); 8a done: FastAPI read-only API on localhost with a separate manual journal, SSE, honest empty states, 13 tests, verified against the real database; fastapi/uvicorn/httpx added (approved in the master prompt) | implemented (Phase 8a) |
| 2026-10-10 | Phase 8b: React/TypeScript/Tailwind web app (8 pages) built in `web/`, served by `arven web`; honest banner on every page, designed empty/error/offline states, EN/RU and dark/light; typechecked, built and checked visually with headless Chrome screenshots on real data; Playwright/Lighthouse (8c) await the owner's OK to add Playwright | implemented (Phase 8b) |
| 2026-10-10 | Phase 8c done with the owner's OK for Playwright: 51 browser tests (desktop + phone), Lighthouse perf>=95 / a11y>=95 / best-practices 100 / SEO 100 on all pages, screenshots committed (fixture data, labelled); mobile performance fixed via lazy loading and by dropping Framer Motion for CSS transitions; Phase 8 complete | implemented (Phase 8c) |
| 2026-10-10 | Web app redesign for the defence audience: Home page with animated hero/pipeline/honesty cards/real equity curve, guided tour, animated command centre; dark default; forward summary gained a `trades` series; 59 browser tests pass; Lighthouse perf>=92, a11y>=95; real-data screenshots committed | implemented (web redesign) |
| 2026-10-10 | Owner asked why only S4-S6 appear: S1-S3 are the Stage 5 voting pipeline (different system); added a combined S1+S2+S3 card to Overview/Strategies and re-ran the pipeline under CFD costs: development -17.4 % (gross -11.1 %), validation -9.9 % (gross -1.6 %) - no edge even before costs; sealed test untouched | recorded (S1-S3 in UI + CFD re-run) |
| 2026-10-10 | Owner's own method formalised as S7 (spec approved), detector + owner review page built; S4 kept unchanged as the control; backtest of S7 deferred until the owner has checked the detector's setups | implemented (S7 detector) |
| 2026-10-10 | S7 detector v2 from the owner's round-1 labels: straightness rule, zone-broken-by-impulse rule (1 ATR / 2x volume, analyst's thresholds, owner: "don't know, continue"), variant 11 (leg beyond the line's first anchor, baseline skip), entry search from the arming bar; round-2 sample exported for the owner | implemented (S7 detector v2) |
| 2026-10-11 | S7 owner check round 2: labelling stopped ("unsure" 74 %); variants 12 (break = first line close) and 13 (line from the major high) pre-registered, owner chose "test both"; baseline unchanged | implemented (S7 variants 12/13) |
| 2026-10-11 | S7 evaluation stage: plan + simulator + study; entry search from the arming close (look-ahead fix, spec §3 design change); variant 14 zone convention (owner: test both); development selection (21 configs) picked 15m/FVG/0.382/E3/S1/shallow zone, CFD +47.6 R / 167 trades in-sample; validation awaits the owner | implemented (S7 evaluation, development) |
| 2026-10-11 | S7 validation run once (owner: "commit and run validation"): CFD -3.05 R / 102 trades, mean R inside the random-entry control; development result not replicated; S7 EXPERIMENTAL, no post-validation tuning | recorded (S7 validation) |
| 2026-10-11 | Owner: no endless new strategies (S8 draft dropped); cost check shows validation flat even at zero costs; $1000 account replay (1 % risk, 0.01 lots, stop loss <= 5 %) and the read-only "S7 trades" page added | implemented (S7 trades page) |
| 2026-10-11 | Edge-lab walk-forward search (22 tries) found "funding_oi"; pre-registered as "Crowded Shorts" (docs/strategy_crowded_shorts.md); forward OI ingested for 2026-07..10; sealed test run once with the owner's go: CONFIRMED by the rule, CFD +1.68 R on 25 trades (PF 1.27, mean R +0.067, inside the random control), BTC -37.3 % | recorded (sealed test used) |
| 2026-10-11 | S7 trade management (owner's breakeven/ladder/runner ideas): paper tracker gained an optional stop ladder (tested, default off); 5 variants pre-registered, chosen on development (PRE_BE_LADDER +48.7 R vs V0 +47.6) - validation -8.0 vs -3.1, forward (S7's first run on 2026-07..10) -6.3 vs -7.3 R: no variant fixes S7, the entry has no out-of-sample edge. Risk check: stops never moved; planned risk 0.5-1.86 % of equity because of 0.01-lot rounding / the minimum-lot rule, 0 trades skipped by the 5 % limit | recorded (S7 management) |
| 2026-10-11 | Strategies page shows every strategy's trades (S4/S5/S6 replayed from recorded and forward signals with their own ladders, S7, Crowded Shorts; CFD costs, $1000 account) via scripts/strategy_trades_export.py and read-only /api/strategy_trades; S6 is positive in all three periods (+14.0 / +7.5 / +3.1 R, forward only 8 trades) | implemented (strategy trades page) |
| 2026-10-11 | S7 SMC-zone entry filter (owner: "try your idea"; scripts/research/s7_zone_filter.py, selected config unchanged, one trade at a time re-applied, CFD): A = iFVG in zone: dev +30.95 R (71), val +8.89 R (44; x4 -0.31, perp -4.76), forward -4.02 R (5, 1 win); B = 3+ zone types: dev +27.68 R (59), val +5.61 R (37), forward -0.24 R (6); no filter forward -7.28 R (21). Idea came from dev+val, so forward is the only clean check and does not confirm it; samples tiny - lead only, not a rule | recorded (S7 zone filter) |
| 2026-10-11 | Owner: finish the project to real-time signals, strategies unchanged, keep them changeable. Built `src/arven/live/` + `config/live.yaml` (registry of strategy kinds, per-strategy enabled/version/params), `arven live run|tick|status|heartbeat`, `scripts/run_live.bat`; live adapters reuse the research code and reproduced every forward S7 and Crowded Shorts research trade bit-identically | implemented (live signal loop) |
| 2026-10-11 | Stage 8 D2 changed: open interest is REST-tailed (public futures/data endpoints, verified against bulk metrics: identical OI, REST timestamp = bulk create_time + 5 min) because Crowded Shorts needs oi_z; architecture.md updated | implemented |
| 2026-10-11 | The live process also runs the Stage 8 hourly paper run (one DuckDB writer); owner approved switching Task Scheduler: 'ARVEN Live' installed (at log-on, restart on failure), 'ARVEN Paper Run' disabled | approved, done |
| 2026-10-16 | Live process ran in a closable console window and stopped for ~46 h after it was closed; now windowless (pythonw) with a 5-minute watchdog trigger, a single-instance lock and a stop file that keeps it stopped | implemented |
| 2026-10-16 | Web app also closable (console window) and went down; added a windowless 'ARVEN Web' task with a 5-minute watchdog and a per-port lock; --log-file logs rotate at 5 MB on start | implemented |
| 2026-10-16 | Added `arven backup` (signal record, runtime state, config; optional consistent DB copy; keeps 10) and docs/DEFENCE_DEMO.md; legacy paper run directories grow ~40 MB/day - retention left open, nothing deleted | implemented |
| 2026-10-16 | Telegram switched on by the owner (.env token + 2 chats, dry_run false); test message and live start alert delivered | done |
| 2026-10-16 | Improvement pass: S7 detector ~5x faster with identical setups; forward review rule (95 % CI, flags only); weekly report; daily backup + paper-run retention in the live process; deployment files for a Linux server; results summary for the thesis | implemented |
