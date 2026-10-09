# ML signal filter for S4 / S5 / S6 (pre-registration, written before any model was trained)

Status: research study. The filter may only **veto** a signal that a strategy already produced (never create a
trade, flip direction or resize). Nothing here claims profitability. The sealed test period is not used.

## 1. Data
- Signals: the unchanged v1 signals of S4 (127 dev / 58 val), S5 (208 / 97) and S6 (342 / 212) recorded by
  `scripts/s4_variant_study.py record` (decision time, side, reference entry, stop, TP ladder).
- Outcome of each signal, evaluated **independently** (no overlap rule, like Stage 6's D3): first-minute-bar fill
  at the decision time, then the Phase 4 `track_signal` replay with the strategy's own legacy exit (TP1 + stop) under
  the CFD cost profile (`config/costs_cfd_justmarkets.yaml`, base). Label `y = 1` if net R > 0. Unresolved at the period end -> dropped.

## 2. Features (all causal)
- Stage 3 columns flagged `required` (`arven.ml.train.logistic_required_columns`), taken from the last hourly feature
  row with `t <= decision time` (the decision time is at or after that row, so nothing later is used).
- Plus: strategy one-hot (S4/S5/S6), side, stop distance / entry, TP1 R-multiple.
- NaN -> training-fold median; standardisation uses training-fold statistics only.

## 3. Model and training protocol (fixed)
- L2 logistic regression (`arven.ml.model.fit_logistic_regression`), `l2` in {10, 100, 1000} chosen by the mean
  walk-forward log-loss on **development**. No gradient boosting: ~680 development signals are too few.
- Walk-forward on development (2020-01-01 -> 2023-07-01), expanding window, `min_train_months=12`,
  `retrain_interval_months=3`, 96 h embargo, training rows purged if their **trade exit** is not before the validation block.
- Decision rule: keep a signal if predicted `P(win) >= base rate of the training rows` (above-average success
  probability). Fixed now; not tuned.

## 4. Success criterion (on validation, evaluated once)
A model trained on **all** development signals with the chosen `l2` and the development base rate as threshold is applied
once to the validation signals. The filter is declared **useful** only if all hold:
1. mean net R of kept validation signals > mean net R of all validation signals;
2. that mean is above the 95th percentile of 2000 random rejections keeping the same number of signals (seeded);
3. at least 60 validation signals are kept.
Otherwise the result is "no value" and the filter is not adopted. Development out-of-fold results (same comparison,
plus ROC-AUC) are reported alongside. Multiple-testing disclosure: this is the first ML-filter attempt on the new strategies;
Stage 6's filter on the old pipeline had ROC-AUC 0.52-0.54 (no skill), which is the realistic prior.

## 5. Results (2026-10-09; `scripts/ml_signal_filter_study.py`, seed 20261009; sealed test untouched)
- Signals with a resolved outcome: development 676 (win rate 35.1 %, mean net R -0.010), validation 365 (38.6 %, +0.074).
- Walk-forward (development): mean log-loss by `l2` = 0.671 / 0.637 / 0.643 -> chosen `l2 = 100`. Out-of-fold (n = 503):
  ROC-AUC **0.572**, log-loss 0.635 vs 0.642 for the base rate - a weak but non-zero ranking skill. Kept 192 of 503:
  mean R **+0.020** vs **-0.042** for all (+3.9 R vs -21.2 R).
- Validation, once, frozen model (threshold = development base rate 0.351): ROC-AUC **0.617**. Kept 210 of 365: mean R **+0.095**
  vs **+0.074** for all (+20.0 R vs +27.1 R in total), win rate 45.2 %. Random rejection keeping the same number: mean +0.078,
  95th percentile **+0.198**. By strategy (total, kept): S4 (58, 1), S5 (96, 50), S6 (211, 159).
- **Verdict: NO VALUE.** Criterion 1 (kept > all) holds, criterion 2 (above the 95th percentile of random rejection) fails,
  criterion 3 (>= 60 kept) holds. The kept set earns +0.095 R per signal, which random selection reaches often.
- Reading: the model learns mostly *which strategy* a signal comes from (it drops almost all S4 signals and keeps S6) and
  has only a weak edge beyond that. Total R on validation is lower with the filter (it removes more winners than losers' cost).
  Consistent with Stage 6's ROC-AUC 0.52-0.54 on the older pipeline. The filter is **not adopted**.
