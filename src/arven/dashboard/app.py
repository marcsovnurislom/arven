"""Stage 10 dashboard - launch with ``arven dashboard`` (wraps ``streamlit run`` as a subprocess) or
directly with ``streamlit run src/arven/dashboard/app.py``.

Read-only over already-written artifacts; see this package's ``__init__.py`` for why it is exempt from the
stage-separation rules the packages below it must follow. No code here computes a trading number - every
figure shown was already written to disk by ``arven backtest run``, ``arven paper run`` or ``arven news
run``. The LLM explain/Q&A calls are triggered only by an explicit button press (never on page load), so
opening the dashboard never spends API budget on its own.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from arven.core.config import load_config
from arven.core.explain_config import load_explain_config
from arven.core.time import from_ms
from arven.dashboard.data import list_runs, load_csv, load_decisions, load_manifest, run_dir_for
from arven.llm.anthropic_client import AnthropicConfigError, AnthropicRequestError
from arven.llm.context import build_context, load_recent_news
from arven.llm.explain import explain_decision
from arven.llm.qa import answer_question
from arven.paper.runs import paper_dir
from arven.runs import backtests_dir

st.set_page_config(page_title="ARVEN", page_icon=":bar_chart:", layout="wide")

APP = load_config()
EXPLAIN_CFG = load_explain_config()

DISCLAIMER = (
    "Research / decision-support tool only - not financial advice. NO_TRADE is the default outcome. "
    "Backtest and paper-trading results include fees, slippage and funding but are not evidence of "
    "future profitability (CLAUDE.md rules 6 and 9)."
)


def _fmt_ms(ms: int | None) -> str:
    return from_ms(ms).isoformat() if ms is not None else "n/a"


def _fmt_num(x: object, spec: str = "{:.2f}") -> str:
    return spec.format(x) if isinstance(x, (int, float)) else "n/a"


def _run_picker(label: str, root: Path) -> tuple[dict, Path] | None:
    entries = list_runs(root / "runs.jsonl")
    if not entries:
        st.info(f"No {label.lower()} runs recorded yet.")
        return None
    options = {f"{e['run_id']}  ({e.get('period', '?')}, {e.get('created_at', '?')})": e for e in entries}
    choice = st.selectbox(label, list(options.keys()))
    entry = options[choice]
    return entry, run_dir_for(root, entry)


def _show_run(entry: dict, run_dir: Path, *, show_decisions: bool) -> None:
    manifest = load_manifest(run_dir)
    if manifest is None:
        st.warning(f"No run.json found under {run_dir}")
        return
    metrics = manifest.get("metrics", {})
    cols = st.columns(4)
    cols[0].metric("Final equity (USDT)", _fmt_num(metrics.get("final_equity")))
    cols[1].metric("Net PnL (USDT)", _fmt_num(metrics.get("net_pnl_usdt")))
    cols[2].metric("Trades", metrics.get("n_trades", "n/a"))
    win_rate = metrics.get("win_rate")
    cols[3].metric("Win rate", f"{win_rate:.1%}" if isinstance(win_rate, (int, float)) else "n/a")

    st.caption(
        f"period={manifest.get('period')}  window=[{_fmt_ms(manifest.get('window_start_ms'))} .. "
        f"{_fmt_ms(manifest.get('window_end_ms'))})  git={manifest.get('git_commit')}"
        f"{'  (DIRTY)' if manifest.get('git_dirty') else ''}  touched_test_set={manifest.get('touched_test_set')}"
    )
    if manifest.get("touched_test_set"):
        st.error(
            "This run touched the SEALED TEST PERIOD - treat its results as a logged, deliberately rare "
            "evaluation, not a routine result (CLAUDE.md rule 3)."
        )

    with st.expander("Full metrics"):
        st.json(metrics)

    equity = load_csv(run_dir, "equity.csv")
    if not equity.empty and "equity" in equity.columns:
        st.subheader("Equity curve")
        st.line_chart(equity.set_index("time_ms")["equity"])

    trades = load_csv(run_dir, "trades.csv")
    if not trades.empty:
        st.subheader(f"Trades ({len(trades)})")
        st.dataframe(trades, width="stretch")
    else:
        st.caption("No trades in this run.")

    if show_decisions:
        _decisions_section(run_dir)


def _decisions_section(run_dir: Path) -> None:
    decisions = load_decisions(run_dir)
    if not decisions:
        st.caption("No decisions.jsonl for this run.")
        return
    st.subheader(f"Decision history ({len(decisions)})")
    labels = [f"{_fmt_ms(d['t_ms'])}  {d['regime']}  -> {d['proposed_action']} / {d['risk_outcome']}" for d in decisions]
    idx = st.selectbox("Decision", range(len(decisions)), format_func=lambda i: labels[i], index=len(decisions) - 1)
    st.json(decisions[idx])
    if st.button("Explain this decision in plain language", key=f"explain-{run_dir}-{idx}"):
        with st.spinner("Asking the LLM to explain (never to decide) ..."):
            try:
                text = explain_decision(decisions[idx], model=EXPLAIN_CFG.llm_model, max_tokens=EXPLAIN_CFG.max_tokens_explain)
                st.success(text)
            except AnthropicConfigError as exc:
                st.warning(str(exc))
            except AnthropicRequestError as exc:
                st.error(f"LLM call failed: {exc}")


def _news_section() -> None:
    st.header("Recent structured news")
    news = load_recent_news(APP, limit=EXPLAIN_CFG.n_news_context)
    if not news:
        st.caption("No news items recorded yet (run `arven news run`).")
        return
    st.dataframe(news, width="stretch")


def _ask_section() -> None:
    st.header("Ask about stored results (research only, never trading advice)")
    question = st.text_input("Question", placeholder="e.g. How many trades did the latest paper run make?")
    if st.button("Ask") and question.strip():
        with st.spinner("Building context from stored data and asking the LLM ..."):
            try:
                context = build_context(APP, n_decisions=EXPLAIN_CFG.n_decisions_context, n_news=EXPLAIN_CFG.n_news_context)
                answer = answer_question(question, context, model=EXPLAIN_CFG.llm_model, max_tokens=EXPLAIN_CFG.max_tokens_qa)
                st.markdown(answer)
            except AnthropicConfigError as exc:
                st.warning(str(exc))
            except AnthropicRequestError as exc:
                st.error(f"LLM call failed: {exc}")


def main() -> None:
    st.title("ARVEN - decision-support dashboard")
    st.caption(DISCLAIMER)

    tab_paper, tab_backtest, tab_news, tab_ask = st.tabs(["Paper (forward)", "Backtests", "News", "Ask"])

    with tab_paper:
        picked = _run_picker("Paper run", paper_dir(APP))
        if picked:
            _show_run(*picked, show_decisions=True)

    with tab_backtest:
        picked = _run_picker("Backtest run", backtests_dir(APP))
        if picked:
            _show_run(*picked, show_decisions=False)

    with tab_news:
        _news_section()

    with tab_ask:
        _ask_section()


main()
