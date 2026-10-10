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
   its high is `H_last`. **Straight, not crooked** (owner's check, round 1): no bar between the first anchor and the
   break may poke above the line by more than `0.8 x ATR` with its wick, even if it closes back below
   (`max_wick_pierce_atr`).
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

7. **Rules from the owner's check, round 1 (2026-10-10, section 8).**
   - **Leg beyond the line's first anchor** (variant 11): if the break leg's high rises above the line's first, highest
     anchor ("all previous highs broken"), the owner does not know whether the method still applies ("I have not had
     such a case"). Baseline: skip; variant: keep. Every setup records `beyond_line_start`.
   - **Zone broken by an impulse** (owner's rule: "if our zone is broken by a big impulse or big volume, we do not
     enter"): a bar whose low runs below the whole entry zone (below fib 0.618, wherever it closes) with a bearish body
     of at least `1 x ATR` **or** a volume at least `2 x` the median of the previous 20 bars cancels the setup. Checked on
     the arming bar by the detector and on every later bar until entry (section 3). The thresholds 1 ATR / 2x are the
     analyst's numbers (the owner did not have exact ones); they are fixed, not optimised.
   - **Zone already reached at arming**: if the arming bar's low already reaches the entry zone (within the touch
     tolerance), the setup records `zone_touched_at_arm`. For E1 a zone reached on the arming bar counts as "price
     traded into the zone" (section 3), so the first lower-TF close back above fib 0.5 after the arming close enters.
8. **Zone convention** (variant 14, owner 2026-10-11: "don't know - test both"). Baseline: the zone is the classic
   50-61.8 % retracement *back from level 1* (`level1 - 0.618 x leg` to `level1 - 0.5 x leg`). Variant: fib 0.5-0.618
   counted *from level 0*, i.e. the 38.2-50 % retracement (the yellow lines on the review page). Fib 0.5 is the same price
   in both. "Fib 0.618" in E2/E4 means the 0.618 line of the convention in use.
9. **Re-arming.** After a setup arms, the leg stays tracked: a close above level 1 moves level 1, and the next pullback
   of `freeze_pullback` arms a *new* setup on the same break (the old one is cancelled by that close, section 3); with no
   new high the leg is dropped once the setup has expired.
10. **Variant 3, FVG:** the break bar must complete a bullish 3-candle gap - its low above the high two bars earlier.

## 3. Entry (variant 5)

- **E1 confirmation (owner's practice, default):** price trades into the entry zone; then a bar on the next lower
  timeframe (`TF` 1h -> 15m, 4h -> 1h, 15m -> 5m) **closes back above fib 0.5** (rejection). Market entry at the
  next bar open (Stage 4 fill rule, broker-cost slippage).
- **E2 limit at 0.618.**
- **E3 limit at 0.5.**
- **E4 split:** half at 0.618, half at 0.5.

**When the entry search starts - design change 2026-10-11 (supersedes the round-1 note "inside the arming bar").** The
search starts at the **close** of the arming bar. Searching inside the arming bar would require the arming-bar rules
(zone broken by an impulse, leg beyond the line's anchor, level 1 set by that bar's own close) to be known before that
bar has closed - a simulator that drops setups because of how their arming bar *closed* while entering inside it would
discard losing trades with hindsight (look-ahead bias). The owner's "missed retest" concern is handled instead by the
§2.7 rule (a zone reached on the arming bar counts for E1) and by the signal being issued at the arming close.

Setup cancelled (no trade) if, at the close of a `TF` bar before entry: the zone is broken by an impulse (§2.7); the bar
closes below level 0; or it closes above level 1 (level 1 moves and the leg may re-arm as a new setup, §2.9); or
`3 x (arm - break)` `TF` bars have passed since arming. Entries inside a `TF` bar come before that bar's close, so a
bar's close never cancels an entry already made inside it; an E1 trigger *at* a close yields to that close's
cancellation.

**Execution model (backtest, `arven.backtest.strategy_s7_sim`; conservative by design):**
- E1: market order at the open of the next lower-TF bar, with the cost profile's adverse slippage.
- Limits (E2-E4): a 1m bar fills a buy limit only if its low trades *through* the limit by the per-side slippage
  fraction (on a CFD the ask must reach the limit), at the limit (or at the open if the bar opened beyond it). If the
  fill bar also touches the stop the leg is stopped there; otherwise exits are tracked from the next 1m bar, so a target
  touched earlier in the fill bar is never credited. Entry fee = taker rate (conservative for a limit).
- E4: the nearer half rests first; once it fills the deeper half works until the first half's first exit event (that bar
  included); each half is sized for 0.5 R of planned risk, so a full loss of both is -1 R.
- Exits: the existing 1m paper tracker (stop beats target in the same bar, one rung per bar), TP1/TP2/TP3 closing
  50/30/20 % of the original size. S3's close-based exit is a time stop at the open after the `TF` close below level 0.
- One trade at a time: setups are taken in order of their entry time; a setup whose entry triggers while a trade is
  open is skipped ("busy"). A trade still open when the data ends is unresolved and excluded; it blocks later setups.
- Missing bars => no trade.

## 4. Stop (always set; variant 6)

- **S1** just inside level 0: fib 0.1 (from the owner's June 2025 BTC example).
- **S2** structural: below level 0 by `0.25 x ATR` (and below the order block if one is used).
- **S3** close-based with a hard stop: exit at the next open if a `TF` bar closes below level 0 (owner's habit),
  plus a hard stop at level 0 minus `1 x ATR` that always protects against spikes.

## 5. Targets and management

- **TP1** = fib 1.0, closes 50 %.
- **TP2** = the nearest resistance between fib 1.272 and 1.618; if none, fib 1.618. Closes 30 %. *Implemented as:*
  prior confirmed swing highs of `TF` and of the next higher TF (15m -> 1h, 1h -> 4h, 4h -> none) known at the arming
  close, within the detector's lookback; bearish OB/FVG are not used for TP2 in this first evaluation (simplification).
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
| 11 | Break leg above the line's first anchor (§2.7) | skip, keep | skip |
| 12 | What is the break (owner, round 2) | close beyond the line **and** `H_last` / range top (§2.2, §2.5); the first close beyond the line | the former |
| 13 | Where the line starts (owner, round 2) | most counted touches among the last 10 swings; the highest swing of the search window (start of the move) | the former |
| 14 | Entry zone convention (owner, 2026-10-11, §2.8) | 50-61.8 % back from level 1; fib 0.5-0.618 from level 0 | the former |

Procedure: the baseline is run first. Then each question is varied **one at a time** on development (2020-01 ->
2023-07), in the order of the table, keeping the best value of each earlier question - **best = highest total R per
100 armed setups, broker (CFD) costs**, among variants with at least 100 trades (clarified before the first run, 2026-10-11: if no option of a question
reaches 100 trades, the earlier value is kept). All results are reported, including the losing ones. The final configuration is run **once** on validation (2023-07 -> 2025-01) and then forward. With 14 questions
(34 option values) the one-at-a-time procedure evaluates at most 21 distinct configurations (1 + the sum of
(options - 1)); that number is part of the
result (multiple testing). (Earlier drafts said 25/27/29 "variants" - those counted option values inconsistently; the
number of configurations actually run is what the report states.)

**Baselines** (CLAUDE.md rule 6), for the selected configuration on the same period and costs: no trade (0 R);
buy-and-hold over the period; and a **random-entry control** - for every S7 trade, entries at uniformly random 1m bars
of the period with the same side, the same stop distance (as a fraction of price) and the same TP R-multiples and
fractions, resolved by the same tracker and costs; 200 seeded draws (seed 7); the report gives S7's mean R against
the control's distribution (mean and 95th percentile).

Analysed but not optimised: win rate and R by confluence score (0-4), by touches, by line length, by session, long
vs short, and - for the owner's open round-2 questions - with vs without a sideways range before the break and by how
many times level 1 moved before it froze ("the high kept updating"). These answer "when does it work and when not".

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

**Round 1 (2026-10-10):** 100 seeded setups (4h 30, 1h 40, 15m 30) marked yes 23 / no 13 / unsure 64, with notes. The
notes grouped into: (a) the leg rose above all previous highs including the line's first anchor - most of the
"unsure", only 1 of 23 "yes" -> variant 11; (b) the zone was run through by a big candle - every such case "no" ->
§2.7 zone-break rule; (c) crooked lines (wicks ~0.9-1.1 ATR through the line) -> §2.1 straightness rule;
(d) the retest happened on the arming bar -> `zone_touched_at_arm` + entry search from the arming bar; (e) long
sideways ranges - present in many "yes" setups as well, so **no** rule or variant was added for them; (f) single
remarks (move fib 1, start the line from an earlier high) - logged, not turned into rules from one or two cases.
With the round-1 rules the detector still finds 21 of the 23 "yes" setups and 4 of the 13 "no" (three remaining are
crooked lines the 0.8 ATR rule does not catch, one "not it"). Labels are archived in `data/s7_review/round1/`.
**Round 2 (2026-10-11):** 91 setups of detector v2 (4h all 21, 1h 40, 15m 30) marked yes 17 / no 7 / unsure 67 -
"unsure" did not shrink (74 % vs 64 %), so further labelling rounds were stopped: what the owner cannot judge by eye
is left to the evaluation. Notes: (a) "fib should start at the first break" - in all 5 such setups the line was
crossed 7-25 bars before the break completed (range rule), which contradicts the owner's own last-touch-high/range-top
rule -> both kept, variant 12; (b) "line should start at an earlier extreme" (5 cases over both rounds) -> variant 13;
(c) "late, the last candle already touched the zone" (~10) - a property of the review format (the arming bar is shown
closed); the entry search inside the arming bar (§3) covers it; (d) ranges and "the high kept updating" stay
"unsure" -> analysed, not optimised (§6); (e) "a single big news candle" - noted; news is not wired into strategies.
Development counts: baseline 4h 21 / 1h 128 / 15m 560; variant 12: 16 / 94 / 395; variant 13: 21 / 126 / 496. Note: 4h
cannot reach the 100-trade minimum of §6 on development.

## 9. Variant log (append-only)

| Date | Variant | Result | Kept? |
|---|---|---|---|
| 2026-10-10 | detector v1 (sections 2.1-2.6) | before the owner's check, two significance rules were added because the first export showed nearly flat lines inside chop and tiny legs: the line must fall at least 2 ATR from its first anchor to its last touch (`min_line_drop_atr`), and the break leg (level 0 to 1) must be at least 3 ATR (`min_leg_atr`); prior-swing "level" zones capped at the 3 most recent. Decided from pictures of the pattern only, no outcome data. Development counts: 4h 45, 1h 248 (1.4/week), 15m 955 setups. | replaced by v2 |
| 2026-10-10 | detector v2 (owner's check round 1, §2.7/§8) | wick straightness 0.8 ATR, zone broken by impulse (wick through the zone + bearish body >= 1 ATR or volume >= 2x 20-bar median), skip legs beyond the line's first anchor (variant 11 baseline), `zone_touched_at_arm` flag. From the owner's labels of pictures only, no outcome data. Keeps 21/23 "yes", 4/13 "no". Development counts: 4h 21, 1h 128, 15m 560. | current |
| 2026-10-11 | variants 12 (break = first close beyond the line) and 13 (line from the major high) added after round 2, owner's choice "test both"; baseline unchanged | counts in §8 | pre-registered |
| 2026-10-11 | evaluation stage: entry/stop/targets (§3-5), re-arming (§2.9), variants 3-FVG and 14 implemented; development selection run (§10) | selected 15m/FVG/0.382/E3/S1/shallow zone: CFD +47.6 R on 167 trades (in-sample, best of 21) | selected for validation |

## 10. Development results (2026-10-11, `scripts/s7_study.py`, `data/s7_study/development.json`)

Development 2020-01-01 -> 2023-07-01, one-at-a-time selection under the broker (CFD) cost profile, metric = total R per
100 armed setups among options with >= 100 trades. **21 configurations evaluated** (multiple testing: the
selected configuration is the best of these on the same data, so its development numbers are optimistic by construction).

| Question | Option | Setups | Trades | Total R | R / 100 setups | Kept |
|---|---|---|---|---|---|---|
| 1 timeframe | `1h` | 158 | 42 | +4.74 | +3.00 |  |
| 1 timeframe | `15m` | 780 | 251 | +3.47 | +0.45 | **yes** |
| 1 timeframe | `4h` | 31 | 10 | -0.34 | -1.09 |  |
| 2 touches | `3` | 780 | 251 | +3.47 | +0.45 | **yes** |
| 2 touches | `2` | 812 | 243 | -20.49 | -2.52 |  |
| 2 touches | `4` | 391 | 133 | -4.14 | -1.06 |  |
| 3 impulse on the break | `none` | 780 | 251 | +3.47 | +0.45 |  |
| 3 impulse on the break | `body_1atr` | 723 | 235 | -4.20 | -0.58 |  |
| 3 impulse on the break | `fvg` | 421 | 156 | +9.23 | +2.19 | **yes** |
| 4 level-1 freeze | `0.236` | 421 | 156 | +9.23 | +2.19 |  |
| 4 level-1 freeze | `0.382` | 312 | 171 | +12.69 | +4.07 | **yes** |
| 5 entry | `E1` | 312 | 171 | +12.69 | +4.07 |  |
| 5 entry | `E2` | 312 | 153 | +22.76 | +7.29 |  |
| 5 entry | `E3` | 312 | 196 | +22.90 | +7.34 | **yes** |
| 5 entry | `E4` | 312 | 196 | +20.78 | +6.66 |  |
| 6 stop | `S2` | 312 | 196 | +22.90 | +7.34 |  |
| 6 stop | `S1` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 6 stop | `S3` | 312 | 193 | +13.35 | +4.28 |  |
| 7 breakeven after TP1 | `False` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 7 breakeven after TP1 | `True` | 312 | 206 | +40.71 | +13.05 |  |
| 8 minimum R to TP1 | `None` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 8 minimum R to TP1 | `1.0` | 312 | 200 | +41.76 | +13.39 |  |
| 9 touch counting | `False` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 9 touch counting | `True` | 340 | 212 | +39.88 | +11.73 |  |
| 10 level 0 after a range | `False` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 10 level 0 after a range | `True` | 313 | 200 | +35.10 | +11.21 |  |
| 11 leg beyond the line's anchor | `True` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 11 leg beyond the line's anchor | `False` | 706 | 364 | -20.03 | -2.84 |  |
| 12 break definition | `False` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 12 break definition | `True` | 655 | 387 | +41.68 | +6.36 |  |
| 13 line start | `False` | 312 | 200 | +41.76 | +13.39 | **yes** |
| 13 line start | `True` | 306 | 202 | +34.58 | +11.30 |  |
| 14 zone convention | `False` | 312 | 200 | +41.76 | +13.39 |  |
| 14 zone convention | `True` | 262 | 167 | +47.56 | +18.15 | **yes** |

Selected: 15m timeframe, 3 touches, FVG on the break, level 1 frozen at a 0.382 pullback, E3 (limit at fib 0.5), stop S1 (fib
0.1), no breakeven, no minimum R, clustered touches, level 0 = last low, legs beyond the line's anchor skipped, break = last
touch high / range top, line with most touches, **shallow zone** (fib 0.5-0.618 from level 0).

| Configuration | Costs | Trades | Win rate | Mean R | Total R | Return at 1 % risk | Max DD at 1 % risk |
|---|---|---|---|---|---|---|---|
| baseline (1h, all defaults) | CFD | 42 | 54.8% | +0.113 | +4.74 | +4.7% | 3.0% |
| baseline (1h, all defaults) | CFD, spread x4 | 42 | 54.8% | +0.082 | +3.46 | +3.3% | 3.0% |
| baseline (1h, all defaults) | perp (5 bp taker) | 42 | 54.8% | +0.043 | +1.80 | +1.6% | 3.3% |
| baseline (1h, all defaults) | perp, stress | 42 | 54.8% | +0.003 | +0.13 | -0.0% | 3.7% |
| selected | CFD | 167 | 55.7% | +0.285 | +47.56 | +58.5% | 8.5% |
| selected | CFD, spread x4 | 155 | 51.6% | +0.151 | +23.43 | +24.7% | 9.4% |
| selected | perp (5 bp taker) | 165 | 46.1% | +0.060 | +9.89 | +8.9% | 11.8% |
| selected | perp, stress | 158 | 41.8% | -0.046 | -7.21 | -8.2% | 14.9% |

Baselines (same period): no trade 0 R; buy-and-hold **+323.7%**; random-entry control (same side, stop distance and
TP R-ladder as each selected trade, 200 draws, CFD costs): mean R -0.039, 5th-95th percentile -0.198 to +0.110
vs S7 selected **+0.285**. The control measures the trade geometry alone, not the selection over 21 configurations.

Breakdowns of the selected configuration (CFD; analysed, not optimised):

| Dimension | Group | Trades | Total R | Mean R |
|---|---|---|---|---|
| side | long | 76 | +21.16 | +0.278 |
| side | short | 91 | +26.40 | +0.290 |
| confluence_score | 1 | 29 | -1.54 | -0.053 |
| confluence_score | 2 | 82 | +23.60 | +0.288 |
| confluence_score | 3 | 51 | +26.37 | +0.517 |
| confluence_score | 4 | 5 | -0.87 | -0.173 |
| touches | 3 | 124 | +45.68 | +0.368 |
| touches | 4 | 31 | -5.27 | -0.170 |
| touches | 5 | 11 | +5.19 | +0.471 |
| touches | 6 | 1 | +1.96 | +1.965 |
| range_before_break | False | 112 | +27.19 | +0.243 |
| range_before_break | True | 55 | +20.37 | +0.370 |
| level1_moves | 0 | 50 | +22.34 | +0.447 |
| level1_moves | 1-2 | 66 | +3.38 | +0.051 |
| level1_moves | 3+ | 51 | +21.85 | +0.428 |
| zone_touched_at_arm | True | 167 | +47.56 | +0.285 |

Reading: under CFD costs the selected configuration's mean R (+0.285) sits above the random-entry control's 95th
percentile, but (1) it was chosen as the best of 21 configurations on this same data; (2) costs are the swing factor -
with the spread stressed x4 the total halves, and under perp costs it is +9.9 R (negative under stress); (3) at 1 %
risk it returned far less than buy-and-hold in this strongly rising period. Every selected trade has
`zone_touched_at_arm = True` by construction (freeze at 0.382 = the shallow zone's near edge). Not evidence of
profitability; the decisive step is the single, unchanged run on validation (2023-07 -> 2025-01), awaiting the owner's go.
