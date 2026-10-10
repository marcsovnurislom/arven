# Strategy S7 - "Trend-Break Fib Retest" (the owner's own method) - SPECIFICATION DRAFT

Status: **approved by the owner 2026-10-10 ("da nachinay detektor"); detector implemented (section 8 stage), no backtest run yet.** Nothing here has been run. Every
parameter is either the owner's own stated rule or a small, pre-registered set of variants that the data (not
intuition, not hindsight) will choose between on the development period. The sealed test period is not used.
Instrument: **BTC/USDT only** (gold may follow later). No real orders (CLAUDE.md rule 12).

## 0. Source of the rules

The owner's description (2026-10-10, chat) and the owner's own chart analyses (screenshots 2025-02 to 2026-10, used
only to understand the method, never as training data or to tune numbers). Where the owner said "I don't know" or
"by intuition", this spec lists variants instead of guessing.

## 1. The pattern in one paragraph (long; short is the exact mirror)

A descending trendline that price has touched several times is broken by a candle that closes at or above the last
touch's high. After the break, price makes a new high and starts to pull back. Fibonacci is drawn from the last low
before the break (level 0) to the highest *close* of the break move (level 1). The entry zone is 0.5-0.618. Extra
confidence when an order block, fair value gap or support level sits in that zone. Targets: level 1, then the next
resistance between 1.272 and 1.618, then 2.0-2.618. A stop is **always** set.

## 2. Definitions

All on the chosen working timeframe `TF` (§6 variant 1) and only with bars already closed (no look-ahead).
`ATR` = Wilder ATR(14) of `TF`. Swings = confirmed 2-bar fractals (same as S4).

1. **Trendline.** A straight line through confirmed swing highs (descending line for longs). A *touch* is a bar
   whose high (wick or close - the owner said either counts) comes within `0.25 x ATR` of the line without
   closing more than `0.25 x ATR` above it. Minimum number of touches: variant 2. The last touch is `T_last`;
   its high is `H_last`.
2. **Break.** The first bar after `T_last` that closes above the line **and** closes at or above `H_last`
   (owner's mandatory rule). Impulse condition: variant 3.
3. **Fibonacci anchors.** Level 0 = the lowest low between `T_last` and the break bar (the last low before the
   break). Level 1 = the highest **close** (not wick) since the break. While price keeps making higher closes,
   level 1 moves up with them (owner: "we don't know which high to use while it keeps updating"); level 1 is
   **frozen** once price has pulled back from it by a fixed fraction of the leg (variant 4). Only then is the
   setup armed.
4. **Entry zone.** `[fib 0.618, fib 0.5]` of the frozen leg.
5. **Sideways ranges (owner, 2026-10-10: "after 2-3 touches a range often starts and its highs keep touching the
   line many times, although they are not real highs").** In a range the descending line drifts down into flat
   range highs, so the line gets "touched" again and again and is finally "broken" by sideways drift, not by an
   impulse. Rules:
   - **Touch clusters.** Touches are counted as *clusters*: a new touch counts only if, since the previous counted
     touch, price has fallen at least `1 x ATR` below the line and at least 5 bars have passed. Ten range highs
     tapping the line in a row therefore count as **one** touch (variant 9 compares this with counting every touch).
   - **Range detection.** A range is active when the last 12 or more bars all lie inside a band whose height is at
     most `3 x ATR`. Its top is the highest high of those bars, its bottom the lowest low.
   - **Break out of a range.** If a range is active, the break is complete only when price has closed above the
     line **and** above the **range top** (not only above `H_last`). The two closes may happen on **different
     bars, in either order** (usually the line is crossed first by sideways drift, the range top later); the break
     bar is the bar that completes the second condition. The impulse condition of variant 3 is mandatory for that
     completing bar (body >= 1 ATR) - a drift through the line inside the range alone is never a break. The pending
     break is cancelled if, before it completes, a bar closes below the range bottom. *Confirmed by the owner
     2026-10-10: "wait for the break of both the range and the trendline; it does not have to be one candle".*
   - **Level 0 after a range** (variant 10): the last low before the break (default) or the range bottom.
6. **Confluence zones** (scored, never required): within the entry zone or within `0.25 x ATR` of it -
   - bullish **order block**: the last bearish candle before the impulse that broke structure (full candle range,
     skipped if the candle is larger than `2 x ATR` - owner: "if it is not too huge");
   - bullish **fair value gap**: 3-candle gap, high of candle 1 below low of candle 3, untouched since;
   - bullish **inverse FVG**: a bearish FVG that price has since closed through;
   - **support** (SnR/SnD): a prior confirmed swing high or low on `TF` or the next higher timeframe.
   `confluence = number of distinct zone types present (0-4)`. Recorded for every setup and analysed, not used to
   filter in the first evaluation.

## 3. Entry (variant 5)

- **E1 confirmation (owner's practice, default):** price trades into the entry zone; then a bar on the next lower
  timeframe (`TF` 1h -> 15m, 4h -> 1h, 15m -> 5m) **closes back above fib 0.5** (rejection). Market entry at the
  next bar open (Stage 4 fill rule, broker-cost slippage).
- **E2 limit at 0.618.**
- **E3 limit at 0.5.**
- **E4 split:** half at 0.618, half at 0.5.

Setup cancelled (no trade) if, before entry: a bar closes below level 0; or price closes above level 1 again
(level 1 then moves and the setup re-arms per §2.3); or 3 x (break-to-freeze duration) bars pass.

## 4. Stop (always set; variant 6)

- **S1** just inside level 0: fib 0.1 (from the owner's June 2025 BTC example).
- **S2** structural: below level 0 by `0.25 x ATR` (and below the order block if one is used).
- **S3** close-based with a hard stop: exit at the next open if a `TF` bar closes below level 0 (owner's habit),
  plus a hard stop at level 0 minus `1 x ATR` that always protects against spikes.

## 5. Targets and management

- **TP1** = fib 1.0, closes 50 %.
- **TP2** = the nearest resistance (prior swing high, bearish OB or FVG on `TF` or the higher TF) between fib 1.272
  and 1.618; if none, fib 1.618. Closes 30 %.
- **TP3** = fib 2.0 (fib 2.618 is reported as an alternative, not traded). Closes 20 %.
- Variant 7: stop to breakeven after TP1 (yes/no).
- **Minimum reward-to-risk:** variant 8 - none, or skip the trade if TP1 is less than 1.0 R away (the owner did not
  know; the data will show whether such trades are worth taking).

## 6. Variants and how one is chosen (pre-registered)

| # | Question | Variants | Baseline |
|---|---|---|---|
| 1 | Timeframe (owner: "higher TF may be better") | 15m, 1h, 4h | 1h |
| 2 | Touches on the line | 2, 3, 4+ | 3 |
| 3 | Impulse on the break | none; break-bar body >= 1 ATR; FVG created by the break | none |
| 4 | When level 1 freezes | pullback of 0.236 or 0.382 of the leg | 0.236 |
| 5 | Entry | E1, E2, E3, E4 | E1 |
| 6 | Stop | S1, S2, S3 | S2 |
| 7 | Breakeven after TP1 | no, yes | no |
| 8 | Minimum R to TP1 | none, 1.0 | none |
| 9 | Counting touches | clusters (§2.5), every touch | clusters |
| 10 | Level 0 when a range preceded the break | last low before the break, range bottom | last low |

Procedure: the baseline is run first. Then each question is varied **one at a time** on development (2020-01 ->
2023-07), in the order of the table, keeping the best value of each earlier question - **best = highest total R per
100 armed setups, broker (CFD) costs**, among variants with at least 100 trades. All results are reported, including
the losing ones. The final configuration is run **once** on validation (2023-07 -> 2025-01) and then forward. 25
variants are evaluated in total; that number is part of the result (multiple testing).

Analysed but not optimised: win rate and R by confluence score (0-4), by touches, by line length, by session, long
vs short. These answer "when does it work and when not".

## 7. Risk and sizing

Every result is measured in **R** (1 R = the planned loss if the stop is hit), so the evaluation does not depend on the
risk percentage. For any account use, the default is **1 % of equity per trade**, never more than one open trade, a
daily loss limit of 3 %, and a stop on every trade - the owner's history (losses of 20-40 % of the balance on one trade
without a stop) is exactly the failure this rule prevents.

## 8. Before any backtest: owner check of the detector

The detector is run on development-period BTC charts and produces images of the setups it finds (line, touches,
break, Fibonacci, zones, entry, stop, targets). The owner marks each as "this is my pattern" or "not my pattern".
This checks the **definition**, not the outcome: the images show only what was known at the entry time (no future
bars), so the owner's judgement cannot leak results into the rules.

## 9. Variant log (append-only)

| Date | Variant | Result | Kept? |
|---|---|---|---|
| 2026-10-10 | detector v1 (sections 2.1-2.6) | before the owner's check, two significance rules were added because the first export showed nearly flat lines inside chop and tiny legs: the line must fall at least 2 ATR from its first anchor to its last touch (`min_line_drop_atr`), and the break leg (level 0 to 1) must be at least 3 ATR (`min_leg_atr`); prior-swing "level" zones capped at the 3 most recent. Decided from pictures of the pattern only, no outcome data. Development counts: 4h 45, 1h 248 (1.4/week), 15m 955 setups. | current |
