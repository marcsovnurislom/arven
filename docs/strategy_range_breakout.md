# Strategy S5 - "Squeeze-Breakout" (specification, written before any code or result)

Status: EXPERIMENTAL. Same methodology as S4 (`docs/strategy_impulse_retest.md` section 9): the parameters below
are fixed now and are **never fitted**; the strategy is evaluated once on development, once on validation, the
sealed test is not used. A negative result is reported as is. Nothing here claims profitability.

## 1. Idea in one paragraph
When BTC trades in an unusually tight range for about a day (a "squeeze"), a close beyond the range edge in the
direction of the 4h trend often starts a larger move. S5 enters on that first 15m close beyond the edge, puts the
stop at the middle of the range (a breakout that falls back to the middle has failed) and aims at multiples of
the range width.

## 2. Timeframes and data (same wiring as S4)
- `context_tf` = 4h: direction filter. `ema_slope_50` of the latest closed 4h bar (`engine.features`, same as S4):
  slope > 0 allows only longs, slope < 0 only shorts, NaN or 0 means no trade.
- `setup_tf` = 1h: the range and the ATR. `trigger_tf` = 15m: the breakout close. Provider is dispatched on 15m events.
- Everything uses bars with `available_at <= decision time` (`BarSeries.available_until`), truncate-then-compute.

## 3. Definitions (all fixed)
- `N = 24`: the range is the last 24 **closed** 1h bars: `hi = max(high)`, `lo = min(low)`, `width = hi - lo`, `mid = (hi + lo) / 2`.
- `ATR`: Wilder ATR(14) of 1h over the trailing **300** closed 1h bars (bounded window: keeps the cost per decision
  constant and is still strictly causal), value at the last closed 1h bar.
- Squeeze: `width <= 4.0 * ATR` (and `width > 0`, `ATR > 0`).
- Buffer: `0.1 * ATR`.

## 4. Trigger (on 15m)
Let `c` = close of the latest closed 15m bar and `c_prev` the one before it.
- Long: `c > hi + buffer` and `c_prev <= hi + buffer` and slope > 0.
- Short: `c < lo - buffer` and `c_prev >= lo - buffer` and slope < 0.
Only a trigger on the current decision bar fires (no stale signals). The strategy does not propose a new entry while
a position is open or an order is pending (provider-level gate, as S4).

## 5. Stop, targets, sizing, confidence
- Stop: long `mid - 0.25 * ATR`; short `mid + 0.25 * ATR`.
- Targets (measured move, from the entry price): `entry +/- k * width` for `k = 1.0, 1.5, 2.0`, closing
  fractions `0.5 / 0.3 / 0.2`. The legacy single-exit backtest uses TP1 (k = 1.0) and the stop only.
- Risk: fixed 1 % of equity per signal (`notional_fraction = 0.01 / stop_pct`), never optimised.
- Confidence: `clamp(1 - width / (4 * ATR), 0.1, 1.0)` (a tighter squeeze reads as more confident).

## 6. Evaluation (decided now)
1. Unchanged parameters on **development** (2020-01-01 -> 2023-07-01) through `EventBacktester` (legacy rendering),
   Stage 4 costs, plus the CFD cost profile (`config/costs_cfd_justmarkets.yaml`) by replaying the recorded
   signals with `scripts/s4_variant_study.py`-style tracker replay when needed; stress x2 (perp) / x4 (CFD).
2. One confirmation on **validation** (2023-07-01 -> 2025-01-01). Forward (>= 2026-07-01) only reported as a count.
3. Anomalies (zero trades, absurd win rate) are investigated before any conclusion.
4. Multiple-testing disclosure: this is the second strategy evaluated in this build-out (S4 first); every variant is logged in section 7.

## 7. Variant log (append-only)
| Date | Variant | Parameters | Result | Kept? |
|---|---|---|---|---|
| 2026-10-09 | v1 | as in sections 3-5 | development: -42.0 % (engine, perp costs), -26 % on CFD costs; validation: -8.1 % (engine), +1.4 % on CFD costs; no edge shown | current, no parameter tuned |

## 8. Results 2026-10-09 (unchanged v1; sealed test untouched)
| | signals (per week) | engine, perp costs (Stage 4 execution) | replay, perp | replay, CFD | replay, CFD stress x4 |
|---|---|---|---|---|---|
| development 2020-01 -> 2023-07 | 208 (1.1) | 208 trades, win 35.6 %, **-42.0 %**, maxDD 43.5 %, Sharpe -1.71 | -49.8 R (-40.1 %) | -29.2 R (-26.3 %), PF 0.78 | -37.1 R (-31.9 %) |
| validation 2023-07 -> 2025-01 | 97 (1.2) | 97 trades, win 45.4 %, **-8.1 %**, maxDD 16.7 %, Sharpe -0.54 | -9.9 R (-9.9 %) | +2.0 R (+1.4 %), PF 1.04 | -4.1 R (-4.6 %) |

Reading: the breakout is found often (about 1.1-1.2 signals per week, twice S4's rate) and wins more often than S4
(36-45 %), but the average trade is negative on development even with spread-only CFD costs (-0.14 R), i.e. the
loss is not a cost artefact: price too often returns to the range middle after the breakout close. Validation is
about breakeven on CFD costs and negative under any stress. **No edge is shown; grade EXPERIMENTAL.** The replay's
validation count (96) differs from the engine's (97) by one unresolved trade at the period end. No parameter was
changed after seeing these numbers.
