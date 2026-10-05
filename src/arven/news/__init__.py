"""Stage 9b: news ingestion and LLM structuring into a fixed schema.

Forward-only by design (architecture.md section 10, rule 11 - "LLM-derived news features are only
evaluated historically on periods after the LLM's training cutoff, otherwise only in forward paper
trading"): this package never resolves a ``BacktestPeriod`` at all, has no notion of development/
validation/test, and is never called from any backtest path. It only ever processes news published at
or after the time it is run, so there is no window in which the LLM's own training-knowledge cutoff could
retroactively contaminate a result.

The LLM is never the source of a trading decision (CLAUDE.md rule 9): it only maps already-published text
to a fixed, validated schema (``news.schema.NewsEvent``). Nothing here is wired into the decision or risk
engine - that is a separate, later integration decision, deliberately out of this stage's scope.
"""
