"""ML meta-filter (Stage 6).

Never predicts direction (Stage 5 strategies do that) and never sizes/vetoes on portfolio state
(Stage 5 risk does that). It estimates, for one already-proposed Stage 5 decision, the probability that its
take-profit is hit before its stop-loss/time-limit net of costs, and may only pass or veto — never flip a
direction, create a trade, resize, or touch a risk parameter (``arven.ml.filter.MetaFilter``).

Labels are intentionally forward-looking (``arven.ml.labels``, never imported by ``arven.features``); every
model *feature* is the unmodified, causal Stage 3 ``FeatureView`` plus the Stage 5 ``ProposedDecision``
context — no new indicators, no new leakage surface. Dataset splitting reuses
``arven.core.splitguard.SplitGuard`` exactly as Stage 4/5 do; nothing here builds a parallel
leakage-prevention system.
"""
