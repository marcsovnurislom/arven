"""Rule-based market regime detection (Stage 5).

Pure logic over the Stage 3 causal feature grid (``docs/architecture.md`` section 12): a Trend axis
(``TREND_UP`` / ``TREND_DOWN`` / ``NO_TREND``, from 4h ADX + EMA slope + price-vs-EMA200, confirmed on 1h) and
a Volatility axis (``LOW`` / ``NORMAL`` / ``HIGH``, the percentile rank of trailing ATR%), plus an optional
Stress flag (extreme funding z-score or OI shock). Regime detection knows nothing about strategies, the
decision engine or risk; it only classifies the market.
"""
