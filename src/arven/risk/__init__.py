"""Risk engine (Stage 5): the last gate before a signal reaches the backtester.

Turns a :class:`~arven.decision.engine.ProposedDecision` plus the current portfolio state into a final
:class:`~arven.core.signal.Signal` (or ``None``/veto). It can only reduce size or veto — never create or flip
a direction (``docs/architecture.md`` section 14) — and it does not know which strategy contributed beyond
what it logs for the record.
"""
