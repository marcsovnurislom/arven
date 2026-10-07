"""Stage 10: context-gathering for Q&A reads only already-stored artifacts (paper run manifest/decisions,
news_items/news_events) - no new computation, no network."""

from __future__ import annotations

import json

from arven.data.storage.db import connect
from arven.llm.context import build_context, load_latest_paper_context, load_recent_news


def write_paper_run(app, run_id: str, metrics: dict, decisions: list[dict]) -> None:
    root = app.data.data_dir / "paper"
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "metrics": metrics}), encoding="utf-8")
    with (run_dir / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d) + "\n")
    with (root / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_id": run_id}) + "\n")


def test_load_latest_paper_context_is_none_when_no_run_has_been_recorded(make_config):
    app = make_config()
    assert load_latest_paper_context(app) is None
    assert "No paper-trading run" in build_context(app)


def test_load_latest_paper_context_reads_the_most_recent_runs_manifest_and_decisions(make_config):
    app = make_config()
    write_paper_run(app, "run-1", {"n_trades": 1}, [{"t_ms": 0, "proposed_action": "NO_TRADE"}])
    write_paper_run(app, "run-2", {"n_trades": 3}, [{"t_ms": 1, "proposed_action": "LONG"}])

    ctx = load_latest_paper_context(app)

    assert ctx["run_id"] == "run-2"
    assert ctx["metrics"] == {"n_trades": 3}
    assert ctx["recent_decisions"] == [{"t_ms": 1, "proposed_action": "LONG"}]


def test_load_latest_paper_context_caps_decisions_to_n_most_recent(make_config):
    app = make_config()
    decisions = [{"t_ms": i} for i in range(5)]
    write_paper_run(app, "run-1", {}, decisions)

    ctx = load_latest_paper_context(app, n_decisions=2)

    assert ctx["recent_decisions"] == decisions[-2:]


def test_load_recent_news_is_empty_before_the_database_file_even_exists(make_config):
    """Regression: the very first `arven ask` before any news/paper/backtest run has ever created the
    database file must not crash - missing data stays NO_TRADE-shaped, never an unhandled IOException."""
    app = make_config()
    assert not app.data.database_path.exists()
    assert load_recent_news(app) == []


def test_load_recent_news_is_empty_before_the_news_table_exists(make_config):
    app = make_config()
    connect(app.data.database_path).close()  # schema exists but no rows
    assert load_recent_news(app) == []


def test_load_recent_news_reads_items_joined_with_their_structured_event(make_config):
    app = make_config()
    con = connect(app.data.database_path)
    con.execute(
        "INSERT INTO news_items VALUES ('id1', 'coindesk', 'http://x/a', 'Title A', 0, 0, 0)"
    )
    con.execute(
        "INSERT INTO news_events VALUES ('id1', 'm', 'v1', 'regulatory', 'btc', 'bullish', 0.5, 0.8, 'ok', 'raw', NULL, 0)"
    )
    con.close()

    news = load_recent_news(app)

    assert len(news) == 1
    assert news[0]["title"] == "Title A"
    assert news[0]["event_type"] == "regulatory"
    assert news[0]["direction_bias"] == "bullish"


def test_build_context_includes_both_paper_run_and_news(make_config):
    app = make_config()
    write_paper_run(app, "run-1", {"n_trades": 0}, [])
    con = connect(app.data.database_path)
    con.execute("INSERT INTO news_items VALUES ('id1', 'coindesk', 'http://x/a', 'Title A', 0, 0, 0)")
    con.close()

    text = build_context(app)

    assert "run-1" in text and "Title A" in text
