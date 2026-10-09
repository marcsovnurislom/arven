# When do S4 / S5 / S6 signals win or lose? (pattern study, pre-registered rules)

Status: research. Costs: CFD profile (`config/costs_cfd_justmarkets.yaml`), since the owner will trade on a broker, not on Binance.
Method: `scripts/signal_pattern_study.py`. Only **development** signals (676) are mined; every (feature, tercile) bucket is a
hypothesis, so significance is the family-wise p-value from a permutation of the maximum |t| over all 114 buckets
(2000 shuffles, seed 20261010). Directional features are multiplied by the trade side ("aligned": + = in the trade's direction).

## 1. What development shows (mean net R per signal)
| strategy | signals | mean R | win rate |
|---|---|---|---|
| S4 impulse-retest | 127 | +0.097 | 15.0 % |
| S5 squeeze-breakout | 208 | -0.140 | 36.5 % |
| S6 trend-pullback | 341 | +0.031 | 41.6 % |

Strongest buckets (none significant: the family-wise 95 % bar for |t| is 3.53, the best is 2.50, family-wise p = 0.60):
- low 168 h close-to-close volatility (calm market): +0.234 R (n = 226), positive in both halves of development (+0.44 / +0.12);
- weekend signals: -0.200 R (n = 177), negative in both halves;
- weak 4h trend (ADX <= 21.1): -0.182 R (n = 226), negative in both halves;
- S5 as a whole is the weak strategy (-0.14 R).
**No pattern is statistically established.** They are consistent with common sense (calm markets and clear trends are friendlier to
these strategies; weekend liquidity is poor), which is why they are fixed below as hypotheses, not as findings.

## 2. Rules fixed now (thresholds from development terciles; evaluated once on validation)
- **R1 "no weak trend, no weekend"**: skip a signal if it is on a weekend or the 4h ADX <= 21.12.
- **R2 "calm market only"**: keep a signal only if the 168 h close-to-close volatility <= 0.005419.
Success criterion for each rule on validation (same as `docs/ml_signal_filter.md`): kept mean R > all-signal mean R **and**
above the 95th percentile of 2000 random rejections with the same number kept, with at least 60 signals kept.
Two rules are tested, so a pass is weak evidence at best; a fail closes the question. Sealed test untouched.

## 3. Results (validation, once, 365 signals, all-signal mean R +0.074)
| rule | kept | mean R | total R | random-rejection 95th pct | verdict |
|---|---|---|---|---|---|
| R1 no weak trend, no weekend | 183 / 365 | +0.085 | +15.5 | +0.216 | **FAIL** |
| R2 calm market only | 271 / 365 | +0.035 | +9.5 | +0.156 | **FAIL** |

Both fail: neither rule beats random selection of the same size, and R2 is below the unfiltered mean. The development tendencies
(calm market, trend strength, weekends) did **not** carry over. No improvement of S4/S5/S6 by condition filtering is established.

## 4. Descriptive probe, not a test: agreement between strategies
`data/tmp/confluence_probe.py` (not committed; exploratory): a signal for which a *different* strategy fired on the same side
within 4 hours versus signals that stood alone (net R per signal, CFD costs):
| period | alone | another strategy, same side within 4 h |
|---|---|---|
| development | n = 601, -0.019 R, win 34.1 % | n = 71, **+0.090 R**, win 43.7 % |
| validation | n = 322, +0.028 R, win 37.3 % | n = 43, **+0.424 R**, win 48.8 % |
Opposite-side overlaps were rare (4 and 0). The direction is the same in both periods, but the groups are small (43-71), the
cut was chosen after looking at both periods, and the validation period is therefore no longer clean for this idea. It is a
**hypothesis for forward data** (to be pre-registered before testing), not a result.
