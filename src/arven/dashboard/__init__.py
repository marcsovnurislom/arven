"""Stage 10: a read-only presentation layer over already-written artifacts (backtest/paper run manifests,
equity/trades CSVs, ``decisions.jsonl``, structured news, Stage 10's own explain/Q&A).

Not bound by the stage-1..8 module-separation rules in the same way those packages are bound by each
other (CLAUDE.md rule 7): this package sits *above* all of them and is allowed to import freely, because it
never feeds anything back - it has no write path into the market database, no decision/risk/strategy logic
of its own (rule 9's "LLMs/UI never compute trading numbers" applies here too: every number shown was
already computed and written to disk by an earlier stage's own run), and running it can never trigger a
backtest, a paper tick, or a real order (CLAUDE.md rule 12 - there is no execution code here at all).
"""
