"""Provider-specific LLM client (Stage 9b). CLAUDE.md rule 9: an LLM is never the source of a numeric
trading calculation or decision - this package only ever turns text into a fixed, validated schema
(``news.schema.NewsEvent``) or (later) writes explanations from already-computed data. It never imports
anything from ``decision``, ``risk``, ``strategies``, ``regime``, or ``backtest``.
"""
