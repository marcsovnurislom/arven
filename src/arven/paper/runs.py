"""Stage 8 composition root: REST tail -> resample -> resolve the forward window -> run the real pipeline
through the real, unmodified ``Backtester`` -> write a run artifact exactly like ``arven backtest run``.

No new execution/accounting/decision logic lives here - this module is I/O and composition only, mirroring
``runs.py``'s own role for Stage 4. The one genuinely new piece is the feature table: Stage 4/6/7 all read a
persisted Parquet cache (``data/features/<version>/``, Stage 3's canonical artifact, covering
``history_start -> history_end`` only); the forward period extends past that, so ``load_paper_inputs`` builds
the feature table directly in memory with the same causal ``build_features`` function instead of writing a
second, parallel cache - cheap enough at the full-history size Stage 3 already measured (~7s), and it leaves
the canonical cache (and its documented content hash) completely untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from arven.backtest.marketdata import MarketData, align_funding
from arven.backtest.provider import FeatureData, SignalProvider
from arven.core.backtest_config import BacktestConfig
from arven.core.config import AppConfig
from arven.core.features_config import FeaturesConfig
from arven.core.splitguard import AllowedWindow, BacktestPeriod, SplitViolation
from arven.core.time import from_ms, to_ms, utc_now
from arven.core.timeframes import Timeframe, last_closed_bar_open
from arven.data.reader import load_1m_bars, load_feature_inputs, load_funding_window, open_readonly
from arven.data.download import Downloader
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.rest_ingestion import RestIngestor, RestTailSummary
from arven.data.storage.db import connect, git_commit
from arven.features.builder import build_features, decision_grid
from arven.features.registry import build_registry, definition_hash
from arven.runs import LoadedInputs, RunOutcome, execute_run, make_guard

HOUR_MS = 3_600_000
DAY_MS = 86_400_000
RESAMPLE_BOUNDARY_BUFFER_MS = 2 * DAY_MS  # comfortably more than the largest derived timeframe (4h)


def paper_dir(app: AppConfig) -> Path:
    return app.data.data_dir / "paper"


def latest_forward_window_end_ms(app: AppConfig, now=None) -> int:
    """The exclusive end of the decision grid that makes the most recently closed, available 1h bar's
    close the last decision time - the same "what is usable right now" rule Stage 2/3 already use
    (``core.timeframes.last_closed_bar_open``), applied once, here, by the live loop (not by any pure
    feature/decision/risk code, which never reads the wall clock)."""
    now = now or utc_now()
    delay = timedelta(seconds=app.data.bar_availability_delay_seconds)
    last_open_ms = to_ms(last_closed_bar_open(now, Timeframe.H1, delay))
    return last_open_ms + 2 * HOUR_MS  # bar duration (-> its close, the decision time) + 1h (exclusive bound)


def update_market_data(
    app: AppConfig, con: duckdb.DuckDBPyConnection, end_ms: int, downloader: Downloader | None = None, now=None,
) -> RestTailSummary:
    """REST-tail 1m klines and funding up to the latest fully-closed 1m bar, then resample exactly the range
    the new 1m bars could affect: from a small buffer before whatever was already stored (so the bucket
    straddling old/new data gets rebuilt complete) through the new data's end. This must cover the *entire*
    newly-tailed range, not a fixed lookback - a steady-state hourly tick only adds an hour of new data, but
    a catch-up after a gap (first run, or a missed period) can add months, and a fixed lookback would silently
    leave most of the new range's derived 5m/15m/1h/4h bars unbuilt (found and fixed before this was usable:
    the original fixed 2-day lookback left all but the last 2 days of a 76-day real catch-up un-resampled,
    which starved every feature after it of derived bars and produced zero decisions all period). Open
    interest is not updated here (Stage 8 scope decision, see ``data.adapters.binance_rest``'s module
    docstring): it simply goes stale/NaN for the forward period, which the existing staleness policy already
    handles. ``downloader`` is injectable so tests never touch the real network (mirrors ``Ingestor``'s own
    constructor parameter). ``now`` must be the *same* wall-clock reading ``run_paper_tick`` used for
    ``end_ms`` (never read independently here), so one tick never mixes two different ideas of "now"."""
    last_before_tail = _last_stored_1m_ms(con, app.market.symbol)
    m1_end_ms = to_ms(now or utc_now()) // Timeframe.M1.ms * Timeframe.M1.ms  # last fully-closed 1m bar
    summary = RestIngestor(app, con, downloader).tail(max(m1_end_ms, end_ms))
    if summary.klines_written:
        anchor = last_before_tail if last_before_tail is not None else m1_end_ms
        lo = max(to_ms(app.data.history_start), anchor - RESAMPLE_BOUNDARY_BUFFER_MS)
        resample(con, app.market.symbol, from_ms(lo), from_ms(m1_end_ms), DERIVED_TIMEFRAMES)
    return summary


def _last_stored_1m_ms(con: duckdb.DuckDBPyConnection, symbol: str) -> int | None:
    row = con.execute("SELECT max(open_time_ms) FROM ohlcv_1m WHERE symbol = ?", [symbol]).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def load_paper_inputs(
    app: AppConfig, fcfg: FeaturesConfig, window: AllowedWindow, con: duckdb.DuckDBPyConnection | None = None,
) -> LoadedInputs:
    """The forward-period analogue of ``runs.load_inputs``: 1m bars and funding are read exactly the same
    way (through the same ``AllowedWindow``-gated loaders); the feature table is built fresh in memory
    (see module docstring) instead of read from Stage 3's persisted cache."""
    ranges: list[dict[str, Any]] = []
    own = con is None
    if con is None:
        con = open_readonly(app.data.database_path)
    try:
        bars = load_1m_bars(con, app.market.symbol, window, ranges)
        f_t, f_r = load_funding_window(con, app.market.symbol, window, ranges)
        inputs = load_feature_inputs(con, app, end=from_ms(window.end_ms))
    finally:
        if own:
            con.close()
    interval_ms = app.costs.funding.default_interval_hours * HOUR_MS
    ft, fr = align_funding(f_t, f_r, window.start_ms, window.end_ms, interval_ms)
    market = MarketData(bars["time_ms"], bars["open"], bars["high"], bars["low"], bars["close"], window.start_ms, window.end_ms, ft, fr, interval_ms)

    full_grid = decision_grid(to_ms(app.data.history_start), window.end_ms)
    full_table = build_features(inputs, full_grid, fcfg)
    mask = (full_table.t_ms >= window.start_ms) & (full_table.t_ms < window.end_ms)
    table = full_table.select_rows(mask)
    ranges.append({"dataset": "features", "start_ms": window.start_ms, "end_ms": window.end_ms})

    ready = full_table.columns["feat_ready"] == 1.0
    feature_manifest = {
        "feature_version": fcfg.version,
        "definition_hash": definition_hash(fcfg),
        "features_config_hash": fcfg.config_hash(),
        "data_sha256": full_table.content_sha256(),
        "source_fingerprint": inputs.fingerprint(),
        "first_ready_ms": int(full_table.t_ms[ready][0]) if ready.any() else None,
        "git_commit": git_commit(),
        "note": "built in memory for the forward period; not Stage 3's persisted data/features/<version>/ cache",
    }
    names = tuple(table.columns)
    values = np.column_stack([table.columns[n] for n in names]) if len(table) else np.empty((0, len(names)))
    features = FeatureData(table.t_ms, names, values, feature_manifest["first_ready_ms"])
    return LoadedInputs(market, features, feature_manifest, ranges)


@dataclass(frozen=True, eq=False)
class PaperTickOutcome:
    window: AllowedWindow | None  # None if forward_start has not arrived yet relative to "now"
    rest_summary: RestTailSummary
    run: RunOutcome | None  # None if there is no new decision time to run yet


def run_paper_tick(
    app: AppConfig, fcfg: FeaturesConfig, bt_cfg: BacktestConfig, provider: SignalProvider, *,
    now=None, downloader: Downloader | None = None,
) -> PaperTickOutcome:
    """One ``arven paper run`` invocation: idempotent and catch-up capable (D7) - it always resolves the
    forward window as ``[forward_start, now)`` and replays the *entire* forward history through it, exactly
    like re-running ``arven backtest run --period forward`` with a later ``--end`` each time. There is no
    per-tick state to corrupt or lose: the only growing state is the market database itself."""
    guard = make_guard(app)
    now = now or utc_now()
    end_ms = latest_forward_window_end_ms(app, now)
    with connect(app.data.database_path) as con:
        rest_summary = update_market_data(app, con, end_ms, downloader, now)
    try:
        window = guard.resolve(BacktestPeriod.FORWARD, end_ms=end_ms)
    except SplitViolation:
        # forward_start has not arrived yet relative to "now" - nothing to decide on, not an error.
        return PaperTickOutcome(None, rest_summary, None)
    inputs = load_paper_inputs(app, fcfg, window)
    root = paper_dir(app)
    root.mkdir(parents=True, exist_ok=True)
    outcome = execute_run(app, bt_cfg, fcfg, window, provider, inputs, out_dir=root, extra={"rest_tail": vars(rest_summary)})
    _append_paper_index(root, outcome.manifest)
    return PaperTickOutcome(window, rest_summary, outcome)


def _append_paper_index(root: Path, manifest: dict[str, Any]) -> None:
    """``data/paper/runs.jsonl``: the same append-only index idea ``runs.append_run_index`` uses for
    ``data/backtests/``, kept separate so paper runs are never mixed into the Stage 4 backtest index."""
    import json

    entry = {
        "run_id": manifest["run_id"], "window_start_ms": manifest["window_start_ms"],
        "window_end_ms": manifest["window_end_ms"], "result_hash": manifest["result_hash"],
        "git_commit": manifest["git_commit"], "git_dirty": manifest["git_dirty"], "created_at": manifest["created_at"],
    }
    with (root / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
