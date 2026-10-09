# Proposal: one unified strategy from the six (information only - no code, not wired anywhere)

Status: **proposal for the owner**. Nothing here is implemented or evaluated; every claim marked (hypothesis) must be pre-registered
and tested on forward data before it is believed. Costs assume a broker CFD (spread-based), not Binance.

## 1. What the evidence says about the six strategies
| strategy | idea | signals/week | result (CFD costs) | where it seems to fit |
|---|---|---|---|---|
| trend_momentum (Stage 5) | 1h EMA20 vs EMA50, 4h ADX >= 20 filter | part of pipeline | pipeline -20.3 % dev (perp costs); walk-forward negative in every window | clear 4h trend |
| breakout (Stage 5) | Bollinger squeeze, Donchian edge | part of pipeline | as above | normal/high volatility |
| mean_reversion (Stage 5) | Bollinger z beyond +/-2 plus RSI | part of pipeline | as above | only when there is no trend |
| S4 impulse-retest | strong impulse, Fibonacci retest, trendline break | 0.5-0.7 | dev +7.7 %, val +18.3 % (127/58 trades), ~0 under spread stress | strong 4h trend after an impulse; rare |
| S5 squeeze-breakout | 24 h tight range, 15m close beyond edge | 1.1-1.2 | dev -26 %, val +1.4 % | no robust regime found; weakest |
| S6 trend-pullback | pullback to 1h EMA20, 15m bounce | 1.9-2.7 | dev +5.7 %, val +4.1 % (342/211 trades), ~-5 % under stress | 4h trend present; most frequent |
Honest summary: no single strategy has a reliable edge; the best (S6, S4) are about breakeven to slightly positive on cheap broker costs.
Filtering by conditions (calm market, strong trend, no weekend) did not survive validation; an ML veto filter did not beat random rejection.

## 2. The principle of the unified strategy ("Confluence")
1. **Regime router first.** The 4h trend decides which family may speak: with a trend (4h ADX >= 20 and slope agreeing with
   the price vs EMA200) only the trend-following family (S6, S4, trend_momentum) may fire, in the trend direction; with no trend
   only mean_reversion may fire; S5 and the old breakout stay switched off until they show an edge. Everything else is NO_TRADE.
2. **Agreement raises the grade (hypothesis).** The only pattern that pointed the same way in both periods: when a second,
   independent strategy fires on the same side within ~4 hours, the signal did better (dev +0.09 R vs -0.02 R; val +0.42 R vs
   +0.03 R, 71 and 43 such signals). Proposal: a single-strategy signal is grade B (half the risk, 0.5 %), an agreeing pair is
   grade A (full risk, 1 %). Opposite-direction signals cancel to NO_TRADE (rare in the data).
3. **One position at a time, one exit plan.** The first signal that clears the router opens the trade; others add only to the
   grade/reasons. Exits stay exactly as each strategy defines them (TP ladder + stop); breakeven and fixed 2R/3R targets were tested
   and made S4 worse, so they are not used.
4. **Costs and venue.** Evaluate with the CFD profile (spread ~2.5 bps round trip, swap-free) and always also with the x4 spread
   stress; a result that is positive only without stress is not accepted. Re-measure the real spread on the owner's account first.
5. **Risk.** Fixed fraction per signal, daily loss halt, no signals on stale/missing data (NO_TRADE is the default), no trading
   when the spread is abnormally wide. Position sizing never depends on a model's output.

## 3. What must be true before it is real
- Pre-register the router thresholds and the grade rule, run on development once, confirm on validation once, then collect forward
  paper results; the confluence rule needs fresh data because its idea came from looking at both periods.
- Expectation check: with ~2.5 signals per week in total and a +0.03 to +0.10 R average, the expected edge is small and within
  noise for ~500 trades; the project's value is the honest process, not a promise of profit.
