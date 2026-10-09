# Strategy S6 - "Trend-Pullback" (specification, written before any code or result)

Status: EXPERIMENTAL. Same protocol as S4/S5: parameters fixed now, never fitted; one evaluation on development,
one confirmation on validation, sealed test unused; a negative result is reported as is. No claim of profitability.

## 1. Idea
In an established 4h uptrend (downtrend), buy (sell) when price has pulled back to its 1h moving average and then
shows a small bounce on 15m. The stop sits under the pullback low, so a failed pullback is cut quickly.

## 2. Timeframes (same wiring as S4/S5)
`context_tf` 4h (`ema_slope_50` of the latest closed 4h bar: > 0 longs only, < 0 shorts only, NaN/0 no trade),
`setup_tf` 1h (EMA, ATR, pullback), `trigger_tf` 15m (bounce). Everything uses only bars with
`available_at <= decision time` (truncate first, then compute).

## 3. Definitions (all fixed)
- `EMA` = EMA(20) of 1h closes and `ATR` = Wilder ATR(14) of 1h, both over the trailing 300 closed 1h bars.
- Pullback window `W = 8` last closed 1h bars: `pull_low = min(low)`, `pull_high = max(high)`.
- Long pullback: `pull_low <= EMA + 0.25 * ATR` (price came down to the average) **and** the last closed 1h close `> EMA`
  (it holds above). Short: `pull_high >= EMA - 0.25 * ATR` and last closed 1h close `< EMA`.

## 4. Trigger (15m)
`level` = highest high of the previous 4 closed 15m bars (long) / lowest low (short). Long fires when the latest closed
15m close `> level` and the previous close was not above its own previous-4-bar level (fresh). Short mirrored.
Cooldown: no new signal within 8 hours of the previous signal of this strategy; the provider proposes nothing while a
position is open or an order is pending.

## 5. Stop, targets, sizing, confidence
- Stop: long `min(pull_low - 0.25 * ATR, entry - 1.0 * ATR)`; short mirrored (never tighter than 1 ATR, to keep costs per R small).
- Targets: `entry +/- k * risk` for `k = 1.5, 2.5, 4.0` (R-multiples), close fractions `0.5 / 0.3 / 0.2`.
  The legacy single-exit backtest uses TP1 (1.5 R) and the stop.
- Risk 1 % of equity per signal. Confidence: fixed 0.5 (no information claimed).

## 6. Evaluation
As S5: development (2020-01-01 -> 2023-07-01) through `EventBacktester` with Stage 4 costs plus CFD-cost replay
(`scripts/s4_variant_study.py`, base and stress), then one confirmation on validation. Zero/absurd trade counts are investigated first.
Multiple-testing disclosure: third strategy evaluated in this build-out (S4, S5 before).

## 7. Variant log (append-only)
| Date | Variant | Parameters | Result | Kept? |
|---|---|---|---|---|
| 2026-10-09 | v1 | as sections 3-5 | development: -22.6 % (engine, perp costs), +5.7 % on CFD costs; validation: -13.5 % (engine), +4.1 % on CFD costs; about zero edge | current, no parameter tuned |

## 8. Results 2026-10-09 (unchanged v1; sealed test untouched)
| | signals (per week) | engine, perp costs | replay, perp | replay, CFD | replay, CFD stress x4 |
|---|---|---|---|---|---|
| development 2020-01 -> 2023-07 | 342 (1.9) | 342 trades, win 40.9 %, **-22.6 %**, maxDD 35.3 %, Sharpe -0.53 | -18.8 R (-19.2 %) | +8.0 R (+5.7 %), PF 1.04 | -2.2 R (-4.6 %) |
| validation 2023-07 -> 2025-01 | 212 (2.7) | 211 trades, win 41.7 %, **-13.5 %**, maxDD 21.0 %, Sharpe -0.59 | -14.2 R (-14.6 %) | +5.6 R (+4.1 %), PF 1.05 | -4.0 R (-5.3 %) |

Reading: the most frequent strategy so far (2-3 signals per week, closest to the owner's target) with the same
tiny result in both periods: about +0.025 R per trade on CFD costs, -0.06 R on perp costs, and about zero or
slightly negative as soon as the spread is doubled. Consistent across periods, but the size of the effect is
well inside noise for ~550 trades. **No reliable edge shown; grade EXPERIMENTAL.** Replay counts differ from the
engine by a few unresolved/overlapping trades. No parameter was changed after seeing these numbers.
