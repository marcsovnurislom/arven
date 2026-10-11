# Strategy "Crowded Shorts" (CS) - pre-registration before the sealed test (2026-10-11)

Grade: EXPERIMENTAL until the sealed-test run. Decision support only - it never places an order.

## 1. How it was found

`scripts/research/edge_lab.py` (protocol in its docstring): 19 rule families plus 3 fixed combinations were tested with
a walk-forward on development + validation (2020-01 -> 2025-01): parameters chosen on 12 months, applied to the next
3 months, 14 out-of-sample quarters (2021-07 -> 2024-12). The family "funding_oi" was the only one to pass the
pre-set bar (positive under CFD, CFD x4 and perp costs; Sharpe t-stat 3.17 above the Bonferroni threshold 2.79 for
22 tries; 9/14 quarters positive): out of sample, CFD costs, 1x notional: +111 %, Sharpe 1.69, max drawdown 12 %, in the
market 10 % of the time. **Caveat:** it was designed in round 2 after round 1 showed that funding extremes carry
information, so the Bonferroni bar understates the search.

Robustness (`scripts/research/robust_funding_oi.py`, development + validation only): every point of a 30-point
parameter grid is positive (Sharpe 1.1-1.8, a plateau, not a spike); holding 4-120 h all work (Sharpe 1.5-1.9); entering
1/2/4 h late keeps Sharpe 1.6/1.4/1.4; against 2000 random-entry draws with the same entries and holding times
p = 0.0005; positive in every calendar year (2022: +33 % while BTC fell 82 % in the same quarters). Forward data
(2026-07-01 -> 2026-10-10, never seen, parameters fixed beforehand): 3 trades, all positive, +3.5 % (tiny sample);
the same funding rule *without* the OI condition lost -2.9 % on 14 trades, so the OI condition matters.

## 2. Rules (fixed; nothing is changed after this document)

All on 1h bar closes with the Stage 3 features (leakage-tested); only data available at the close is used.

- **Signal:** `fund_z <= -1.5` (funding z-score: shorts are paying unusually much) **and** `oi_z >= 1.0` (open
  interest high versus its own last 30 days: the shorts are crowded). Long only.
- **Entry:** market buy at the open of the next hour.
- **Exit:** 24 hours after the most recent qualifying signal (a new signal while long extends the hold), or the stop.
- **Stop:** 3 % below the entry fill, always set.
- **Missing funding or OI data => no trade.**
- **Sizing (owner's rule):** risk 1 % of equity at the stop (position = 1 % / 3 % = about 33 % of equity in notional),
  rounded down to 0.01 BTC lots; the minimum lot only while its stop loss stays within 5 % of equity.
- **Costs:** broker CFD profile (spread only, `config/costs_cfd_justmarkets.yaml`); also reported with the spread x4 and
  with perp costs + funding.

Development + validation result with exactly these rules (in-sample for the fixed values, 2020-09 -> 2024-12, 1m bars):
53 trades, win rate 58 %, average trade +2.52 % (about +0.84 R), worst -3.0 %, max drawdown 10.8 % at 1x.

## 3. The sealed test (2025-01-01 -> 2026-07-01) - run once, only with the owner's go

Metrics: number of trades, win rate, mean R, total R, profit factor, max drawdown, the $1000 account at 1 % risk; CFD,
CFD x4, perp; buy-and-hold and a random-entry control (same entries and holding times, 2000 draws) on the same period.

**Confirmed** if, under CFD costs: total R > 0, profit factor >= 1.2, and the result stays positive with the spread x4.
Otherwise **not confirmed**. With an expected 10-25 trades in 18 months the error bars are wide either way; a
confirmation would justify live paper trading, not certainty. The run is logged; the period is not used again.
