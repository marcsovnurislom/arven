# Strategy S4 — "Impulse-Retest"

Status: **spec, written before any implementation** (`docs/ARVEN_MASTER_PROMPT.md` section 5.5 requires
this explicitly). Nothing below is fitted to the data - every number is a round, defensible default chosen
*before* looking at any backtest result, per CLAUDE.md's "do not optimize parameters" and this project's
own "pre-register every parameter" discipline. Section 8 is the mandatory log of every variant tried after
this point (multiple-testing disclosure) - it starts empty and is appended to, never rewritten.

## 0. Origin and honesty constraints

This formalises the owner's own discretionary chart-reading method (described, not shown as labelled
examples): after an impulsive move, price retraces into a confluence zone, breaks the counter-trend line
that was containing the pullback, retests that zone, and then runs toward Fibonacci extensions of the
original impulse. It is a **hypothesis**, not a proven edge - CLAUDE.md rule 6 applies to every result
this strategy ever produces, same as every other strategy in this project.

**What is explicitly not done**: the owner's chart screenshots are not used as training data, as a source
of historical entries/exits, or to tune any parameter below - CLAUDE.md's leakage discipline extends to
"the owner's own hindsight" as a leakage source, not only to future market data. Every parameter here was
chosen from general technical-analysis convention and this project's own existing defaults (ATR period 14,
etc.), not by looking at how well it would have performed.

## 1. Timeframes (`StrategySpec`)

| Role | Timeframe | Role in the setup |
|---|---|---|
| `context_tfs` | 4h | Trend/impulse context: where is the market's larger structure? |
| `setup_tf` | 1h | Where swings, the impulse, and the confluence zone are measured |
| `trigger_tf` | 15m | Where the trendline break + retest is confirmed and the signal fires |

Fixed by the master prompt itself, not chosen here.

### 1.1 What `context_tfs=(4h,)` concretely does

The master prompt names 4h as "context" without specifying the exact filter; this spec makes it concrete,
pre-registered, and reuses Phase 2's own per-timeframe feature rather than inventing a new indicator:

```
long setup allowed only if 4h ema_slope_50 > 0   (engine.features' own column, via MultiTFView)
short setup allowed only if 4h ema_slope_50 < 0
```

A setup whose direction disagrees with the 4h trend slope produces no signal, regardless of how clean the
rest of the pattern is - the impulse must be running *with* the larger structure, not against it. This is
the only place `MultiTFView` is used directly (a single as-of row lookup); §§2-7 operate on raw,
causally-truncated `setup_tf`/`trigger_tf` bar history instead (see `engine/strategy_s4.py`'s own module
docstring for why).

## 2. Causal swing (pivot) detection

A **swing high** at bar `i` on a timeframe is confirmed once bar `i + K` has closed, if
`high[i] > high[i-K : i]` and `high[i] > high[i+1 : i+K+1]` (strictly higher than every bar within `K` on
both sides - the backward side is already known at `i`, the forward side is only known `K` bars later).
Its `available_at` is therefore the close of bar `i + K`, never earlier - this is the point-in-time rule
CLAUDE.md rule 1 asks for, applied to a pattern that is inherently defined by *looking both ways* around a
bar. A **swing low** is the mirror image on `low`.

- **`K = 2`** (on `setup_tf`, i.e. a 2-hour confirmation lag) - the standard "2-bar fractal" convention
  (e.g. Bill Williams' fractals), chosen for being a well-known default, not tuned.
- Implementation: `engine/strategy_s4.py::confirmed_swings(high, low, k)` - pure, causal, returns each
  swing's bar index, kind (high/low), price, and `confirmed_at` index (`i + K`).

## 3. Impulse

The **last confirmed swing-to-swing leg** on `setup_tf` whose size qualifies:

```
impulse_size = |price_at(end_swing) - price_at(start_swing)|
qualifies if impulse_size >= M * ATR_14(setup_tf) at the end swing's own bar
```

- **`M = 3.0`** - an impulse must be at least 3x the prevailing 1h ATR to count as "impulsive" rather than
  ordinary chop. Round number, not tuned.
- Direction: a low-to-high leg is a **bullish impulse** (the strategy then looks for a long on the
  retracement); high-to-low is a **bearish impulse** (short).
- Only the **most recently confirmed** qualifying impulse is ever considered "active" at any decision time -
  an older one is superseded the moment a newer swing extends past it or a new leg qualifies.

## 4. Confluence zone

Per the master prompt's own text, the retracement band is **Fibonacci 0.5-0.618** of the impulse
(measured back from the impulse's *end*, i.e. the point the price must retrace through):

```
long:  fib_band = [end - 0.618 * impulse_size, end - 0.5 * impulse_size]
short: fib_band = [end + 0.5 * impulse_size,   end + 0.618 * impulse_size]
```

**Revision 2026-10-08 (before any evaluation ran - see §11):** the first draft of this section defined the
demand/supply "base candle" as the single bar immediately before the impulse's *starting* swing
(`start_swing_index - 1`). That bar's own price is, by construction, at or very near the impulse's origin -
but `fib_band` sits 38-50% of the way *up* the move from that origin, so the two essentially never overlap
for a real impulsive leg (confirmed empirically before writing any backtest/evaluation code: a hand-built
impulse-retest scenario produced `zone = None` every time with the original definition). This is corrected
here, not hidden - CLAUDE.md's "investigate an anomaly rather than accept it" applies to a strategy's own
geometry just as much as to a "0 trades" backtest result.

**Corrected rule**: the base candle is searched for *within the impulse leg itself* (any `setup_tf` bar
from `start_swing_index` to `end_swing_index` inclusive), nearest the impulse's end first - the first one
found (scanning backward from the end) whose own range overlaps `fib_band` and qualifies by size:

```
base_range = high[i] - low[i]
qualifies if base_range >= N * ATR_14(setup_tf) at bar i, AND [low[i], high[i]] overlaps fib_band
```

This matches the real pattern this strategy formalises better than the original draft: an impulsive leg
often pauses briefly partway through (a small base/consolidation the move "broke out from" on its way to
the swing extreme), and that pause - not the move's literal starting candle - is what price later returns
to retest. If no bar in the leg qualifies, there is no valid zone and the impulse produces no signal, same
as before.

- **`N = 1.0`** - the base candle must be at least as large as the prevailing ATR (filters out a doji or a
  tiny bar as a meaningless "zone"). Round number, not tuned.
- **Overlap rule**: the zone used for the rest of the setup is the **intersection** of `fib_zone` and
  `[low[base], high[base]]`. If the intersection is empty, there is no valid zone and the impulse produces
  no signal - the strategy does not fall back to either range alone.

## 5. Trendline (the counter-trend line containing the pullback)

A line through the **last two confirmed counter-trend pivots** since the impulse's end swing - for a
bullish impulse (long setup), "counter-trend" pivots are **swing highs** (the pullback's own lower highs);
for a bearish impulse, swing lows. Both pivots must be confirmed (§2) and must lie strictly after the
impulse's end-swing bar. If fewer than two such pivots exist yet, there is no trendline and no trigger can
fire.

```
trendline_price(t) = p1 + (p2 - p1) * (t - t1) / (t2 - t1)     (linear interpolation/extrapolation)
```

where `(t1, p1)`, `(t2, p2)` are the two confirmed pivots' own bar-close times and prices, `t1 < t2`.

## 6. Trigger (on `trigger_tf`)

Two conditions, both required, evaluated on `trigger_tf` (15m) bar closes **after** a valid zone and
trendline exist:

1. **Break**: a 15m bar closes beyond the trendline (above it for a long, below it for a short), evaluated
   at that bar's own close time via `trendline_price(t)`.
2. **Retest-and-hold**: on a *later* 15m bar (break bar or after), the bar's low (long) / high (short)
   trades back into the zone band (§4) **and** that same bar's close remains on the breakout side of the
   zone's near edge (does not close back inside/through the zone).

The signal fires on the first 15m bar where condition 2 is satisfied, provided condition 1 was already
satisfied by an earlier (or the same) bar. Both checks use only `trigger_tf` data up to and including the
bar being evaluated - no look-ahead.

If price travels straight through the zone without ever registering a bar that both touches it and holds
it (e.g. one giant bar gaps through everything), **no signal fires** - a clean retest is required by
construction, not approximated.

## 7. Stop and targets

- **Stop**: beyond the zone and the impulse origin, ATR-buffered -
  `stop = zone_far_edge - 0.25 * ATR_14(setup_tf)` for a long (the zone's edge nearer the impulse origin,
  minus a small buffer so ordinary noise cannot stop it out exactly at the level everyone else is
  watching); mirror for a short. **Buffer `0.25`** - round, not tuned.
- **Targets**: Fibonacci extensions of the impulse, **measured from the entry (zone) price**, projecting
  the impulse's own size forward:

  ```
  TP_i_price = entry + side * fib_i * impulse_size      fib_i in {1.0, 1.414, 1.618}
  ```

- **Close fractions**: **50% / 30% / 20%** across TP1/TP2/TP3 - the same round split already used
  throughout this project's Phase 4 fixtures and tests. The **TP2-after-TP1 / TP3-after-TP2 unlock rule**
  is not separate logic: `arven.backtest.paper_tracker` already resolves at most one rung per bar, in
  ladder order (Phase 4) - a rung simply cannot register before the one before it, by construction.
- **R-multiples for the ladder** (`TPLevel.r_multiple`, for `EngineSignal`/the grading gate) are derived
  from these same prices against the stop (`r = side * (TP_i_price - entry) / |entry - stop|`), never
  stored as a second, independently-set number.

## 8. Confidence and risk sizing

- **`confidence`**: a simple, deterministic score in `[0, 1]`, equal to the fraction of the Fib 0.5-0.618
  band actually covered by the overlapping base-candle zone (a fuller overlap is a cleaner, more "textbook"
  confluence) - clamped to `[0.1, 1.0]` so a thin-but-nonzero overlap is never reported as exactly zero
  confidence. Not used to size the position (CLAUDE.md rule 9 - no number here drives execution weighting
  beyond the fixed risk below); shown for context only.
- **`risk_fraction`**: a **fixed 1.0% of equity** per signal, regardless of confidence - the same
  "do not optimise, do not improvise sizing" discipline Stage 5's strategies already follow.

## 9. Evaluation methodology (how §§2-8 above are checked, not tuned)

- **Development backtest**: one run over the development period via `arven.backtest.event_engine.
  EventBacktester` with S4 registered under `Timeframe.M15` (its `trigger_tf`), using its own
  `MultiTFView` rather than the legacy `FeatureView` (S4 is the first consumer of the Phase 1-2 engine
  machinery for a real decision, not just infrastructure tests).
- **Baselines**: no-trade / buy-and-hold / random-entry, same cost model, for comparison - never a ranking.
- **Cost stress**: the same `stress=True` (2x slippage) flag `EventBacktester`/`Simulator` already support.
- **Windowed robustness** in place of Stage 6/7's purged walk-forward: S4 has no fitting step at all (fixed
  parameters, no training), so the purge/embargo machinery built for Stage 6's ML meta-filter (which exists
  specifically to stop a *fitted model* from leaking across a train/validation boundary) does not apply
  here. Instead, S4 is run **separately over several consecutive sub-windows** of the development period
  (plain chronological slicing, `core.splitguard`'s existing `AllowedWindow` machinery, no ML-specific
  splitting code reused) to see whether any edge holds up across different stretches of time, not just the
  whole period pooled together.
- **Per-regime-like breakdown**: S4 cannot import `arven.regime` (the engine module-boundary rule holds
  here too), so results are broken down by **S4's own 4h-context classification** instead of the legacy
  regime detector - a simple, separately-defined label (impulse direction x whether a trade happened),
  documented where it is computed, not a reuse of `regime.detector.Regime`.
- **Forward paper**: once backtest results are in hand, S4 can be registered into a forward/paper run the
  same way Stage 5's pipeline is - producing real forward signals that accumulate over calendar time,
  exactly like every other stage's forward evidence. This cannot be "completed" synchronously; it is
  evidence that accumulates, the same honest framing already used for Phase 5/6's own deferred real-time
  steps.
- **Grading**: the Phase 4 gate (`engine.grading.grade`) is applied to whatever `TrackRecord` the above
  produces - S4 starts at `EXPERIMENTAL` like every strategy does, and nothing in this document promotes
  it early.

## 10. What is explicitly out of scope for this spec

- A second, slower "swing" strategy (Helix-like) - optional, later, its own separate spec.
- Any change to Stage 4's execution model to natively support a multi-rung TP ladder - the ladder is
  resolved by the separate Phase 4 `paper_tracker`, not by `Simulator`; the backtest/WFO/baselines/stress
  evaluation in §9 uses S4's **nearest target (TP1) and its stop only**, exactly like every other
  strategy's existing single-exit backtest, so no change to the shared, already-validated execution layer
  is needed. The full ladder's added realism is evaluated on the forward/paper leg, where it matters most
  for a live product - this is a deliberate, documented methodology choice, not an oversight.
- Parameter search of any kind. If a later session wants to try a different `K`/`M`/`N`/buffer, that is a
  new, logged variant (§11), evaluated the same way, on development data only, never on validation/test.

## 11. Log of every variant tried (append-only, multiple-testing disclosure)

| Date | Variant | Parameters changed from §§2-8 defaults | Result (one line) | Kept? |
|---|---|---|---|---|
| 2026-10-08 | v1 | none | §4's original base-candle definition (`start_swing_index - 1`) found to never geometrically overlap the Fib zone, before any backtest ran - not a tuning change, a definition bug | superseded by v1.1 below |
| 2026-10-08 | v1.1 (this spec) | §4's base-candle search widened to the whole impulse leg (see "Revision" note in §4) - no threshold (`K`/`M`/`N`/buffer/Fib band/extensions) changed | pending full evaluation (7b) | current |
| 2026-10-09 | v1.1 exit-management study (pre-registered below, before any variant was evaluated) | exits only: V0 control, A, B, C, D (see "Pre-registration 2026-10-09") - entry logic, stops and all §§2-8 thresholds unchanged | selected by the pre-registered rule: V0 (control, no change); A and B (breakeven) clearly worse | v1.1 exits unchanged |

### Pre-registration 2026-10-09 (written before any variant result existed)

Motivation: v1.1's development run was -20.5 % with a +878 USDT gross edge eaten by 2 758 USDT of costs; a
diagnostic on the development trades showed 35 % of stopped trades first reached +1 R. The owner asked whether
a breakeven stop / partial profit would help and whether the broker is a JustMarkets MT5 BTCUSD CFD.

- **Signals**: exactly the unchanged v1.1 signals (`scripts/s4_variant_study.py record`), 127 on development
  and 58 on validation. Entry fill = first 1m bar open at the decision time plus adverse slippage (as Stage 4).
- **Variants** (all on the same signals; one open trade at a time per variant, a signal arriving while that
  variant's trade is open is skipped):
  - **V0** control: TP1 (100 %) + original stop = the existing single-exit rendering, replayed on the tracker.
  - **A**: stop moves to the entry fill once price has traded +1 R (effective from the next 1m bar); everything
    else closes at TP1.
  - **B**: A, plus 30 % closed at +2 R; the remaining 70 % to TP1 (if TP1 is nearer than +2 R the +2 R rung is dropped).
  - **C**: single exit at a fixed +2 R, original stop.
  - **D**: single exit at a fixed +3 R, original stop.
- **Cost profiles** (both reported for every variant): `config/costs.yaml` (Binance USDT-perp, default) and
  `config/costs_cfd_justmarkets.yaml` (BTCUSD CFD, JustMarkets MT5 Pro, ~2.5 bps round-trip spread, swap-free;
  the spread is from one public live test, not verified on the owner's terminal). Funding/swap is not modelled
  by the tracker (the perp profile therefore omits ~0.2 R-equivalent of funding that Stage 4 does include - stated, not hidden).
- **Selection rule, fixed now**: under the CFD profile (the venue the owner intends to use), the variant with
  the highest total R on **development**, among those with >= 80 trades. Validation is **not** used to choose:
  it is reported once for all variants as a confirmation (a deliberate, disclosed departure from §10's
  "development only" for parameter search - these are exit-management choices, not parameter searches, and
  every variant is shown, so there is no re-selection). Five variants x two cost profiles are compared: this
  multiple-comparison count is part of the result, and a small positive total R must not be read as an edge.
- **The sealed test (2025-01..2026-07) is not used.**

### Results 2026-10-09 (net R per trade at 1 % risk; no funding/swap in the tracker; sealed test untouched)

| development (127 signals) | perp base | CFD base | CFD stress (x4) |
|---|---:|---:|---:|
| V0 | -21.8 R (-23.3 %) | **+12.3 R (+7.7 %)** | -4.8 R |
| A (BE at +1 R) | -46.7 | -14.4 | -29.4 |
| B (A + 30 % at +2 R) | -46.6 | -14.8 | -30.2 |
| C (fixed +2 R) | -39.0 | -6.7 | -21.5 |
| D (fixed +3 R) | -33.4 | -0.9 | -16.2 |

| validation (58 signals) | perp base | CFD base | CFD stress (x4) |
|---|---:|---:|---:|
| V0 | -0.1 R (-2.6 %) | **+19.5 R (+18.3 %)** | +8.0 R |
| A | -14.3 | +4.0 | +3.3 |
| B | -14.4 | +3.8 | +0.9 |
| C | -11.1 | +7.2 | -2.5 |
| D | +2.0 | +21.7 | +10.6 |

- **Selection (rule fixed in advance): V0** - highest development total R under the CFD profile. D has the
  best validation number, but validation was declared a confirmation, not a selector; D is **not** adopted.
- **Breakeven (A, B) hurts** on both periods and both profiles: win rate falls (A: 8 % on development) because
  trades that retrace to the entry after +1 R are stopped flat (minus costs) and would often have continued.
- **Sanity check**: V0 replayed on the tracker gives win rate 15.0 % and -21.8 R on development under perp costs,
  vs 14.8 % and about -20 R in the Stage 4 engine; the engine filled 108 of the 127 signals and models funding,
  the tracker takes all 127 and has none - the replay is approximate, not byte-identical.
- **Caveats**: 127 + 58 trades; V0 on CFD costs combined is about +0.17 R per trade over 185 trades (roughly
  1 sigma of the per-trade noise); under the x4 spread stress the combined result is about +3 R, i.e. zero.
  Ten comparisons per period were made. The CFD spread (~2.5 bps round trip) is one public 2025 measurement,
  not verified on the owner's terminal. Not evidence of profitability; grade stays EXPERIMENTAL.
