"""``run_live_tick`` on a synthetic database with fake strategies: store, cursors, de-duplication, alerts, stale data
=> no new signals, one failing strategy does not stop the others. Offline (fake REST), no real Telegram."""

from __future__ import annotations

import json

import numpy as np
import pytest
from bt_helpers import bulk_insert_1m

from arven.core.features_config import load_features_config
from arven.core.live_config import LiveConfig
from arven.core.time import from_ms
from arven.data.download import Downloader, RetryPolicy
from arven.data.resample import DERIVED_TIMEFRAMES, resample
from arven.data.storage.db import connect
from arven.engine.grading import Grade
from arven.engine.signal import EngineSignal, SignalVersions, TPLevel
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.engine.signal_store import read_signals, read_updates
from arven.live.base import LiveOutcome
from arven.live.service import complete_through_ms, run_live_tick
from rest_helpers import FakeBinanceRestOpener

MIN = 60_000
H = 3_600_000
DAY = 86_400_000
T0 = 1_609_718_400_000  # 2021-01-04 00:00 UTC
N_MIN = 5 * 24 * 60
LAST_1M = T0 + (N_MIN - 1) * MIN


def _splits() -> dict[str, str]:
    day = lambda n: from_ms(T0 + n * DAY).date().isoformat()  # noqa: E731
    return {"default__data__history_start": day(0), "splits__development__start": day(0), "splits__development__end": day(1),
            "splits__validation__start": day(1), "splits__validation__end": day(2), "splits__test__start": day(2),
            "splits__test__end": day(3), "splits__forward_start": day(3)}


@pytest.fixture
def env(make_config, tmp_path):
    app = make_config(**_splits())
    con = connect(app.data.database_path)
    rng = np.random.default_rng(1)
    px = 100 + np.cumsum(rng.normal(0, 0.05, N_MIN))
    bulk_insert_1m(con, [("BTCUSDT", T0 + k * MIN, T0 + (k + 1) * MIN, p, p + 0.1, p - 0.1, p, 1.0, 1.0, 1, 0.5, 0.5, "seed", 0) for k, p in enumerate(px)])
    resample(con, "BTCUSDT", from_ms(T0), from_ms(T0 + N_MIN * MIN), DERIVED_TIMEFRAMES)
    con.close()
    config_dir = tmp_path / "config"  # make_config wrote the repo config here; the cost profile file must exist too
    import shutil
    from pathlib import Path

    shutil.copy(Path(__file__).resolve().parents[2] / "config" / "costs_cfd_justmarkets.yaml", config_dir / "costs_cfd_justmarkets.yaml")
    return app, load_features_config(), config_dir


def _downloader(app):
    return Downloader(RetryPolicy.from_config(app.download), opener=FakeBinanceRestOpener([], []), sleep=lambda s: None)


def _sig(sid: str, t: int) -> EngineSignal:
    return EngineSignal(symbol="BTCUSDT", side=1, strategy_id=sid, strategy_version="v1", grade=Grade.EXPERIMENTAL, event_time_ms=t,
                        entry_reference=100.0, stop=99.0, tp_ladder=(TPLevel(1.0, 1.0, 101.0),), risk_fraction=0.01, confidence=0.5,
                        regime="n/a", reasons=("fake",), risk_checks=(), versions=SignalVersions("v", "h", None))


class Fake:
    def __init__(self, sid: str, times: list[int], fail: bool = False):
        self.strategy_id, self.title, self.times, self.fail = sid, sid, times, fail
        self.scans: list[tuple[int, int]] = []

    def scan(self, ctx, after, through, stored):
        self.scans.append((after, through))
        if self.fail:
            raise RuntimeError("boom")
        return [_sig(self.strategy_id, t) for t in self.times if after < t <= through]

    def resolve(self, ctx, s):
        if s.event_time_ms + 30 * MIN > ctx.through_ms:
            return LiveOutcome(s, (), "open")
        return LiveOutcome(s, (SignalUpdate(s.signal_id, s.event_time_ms + 30 * MIN, SignalUpdateKind.CLOSED, "reason=STOP;fraction=1"),), "closed", -1.0)


def test_complete_through_needs_the_data_and_the_delay():
    assert complete_through_ms(None, 0, 0) is None
    t = 1000 * 15 * MIN
    assert complete_through_ms(t - MIN, t + 10_000, 5_000) == t  # the 1m bar ending at the close is stored, delay passed
    assert complete_through_ms(t - 2 * MIN, t + 10_000, 5_000) == t - 15 * MIN  # its last minute is missing
    assert complete_through_ms(t - MIN, t + 2_000, 5_000) == t - 15 * MIN  # too early


def test_tick_stores_signals_once_tracks_them_and_alerts_only_recent_ones(env):
    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    through = (LAST_1M + MIN) // (15 * MIN) * (15 * MIN)
    fwd = T0 + 3 * DAY
    a = Fake("fake_a", [fwd + 15 * MIN, through - 60 * MIN, through])
    queued = []
    live = LiveConfig(alert_recency_hours=2)
    out = run_live_tick(app, fcfg, live, config_dir, now=now, downloader=_downloader(app), chat_ids=frozenset({"1"}), strategies=[a],
                        telegram_enqueue=lambda con, sid, et, chat, text, now_ms: queued.append((sid, et, chat)))
    assert out.status == "ok" and out.through_ms == through
    root = app.data.data_dir / "signals"
    assert [s.event_time_ms for s in read_signals(root, "fake_a")] == a.times
    assert len(read_updates(root, "fake_a")) == 2  # the last one is still open
    kinds = sorted(et.split(":")[0] for _, et, _ in queued)
    assert kinds == ["new_signal", "new_signal", "update"]  # the old signal and its close are stored but not alerted
    summary = json.loads((app.data.data_dir / "paper" / "strategies_summary.json").read_text(encoding="utf-8"))
    assert summary["strategies"]["fake_a"]["signals"] == 3 and summary["strategies"]["fake_a"]["closed"] == 2
    assert json.loads((app.data.data_dir / "paper" / "strategies_cursor.json").read_text(encoding="utf-8")) == {"fake_a": through}

    queued.clear()
    again = run_live_tick(app, fcfg, live, config_dir, now=now, downloader=_downloader(app), chat_ids=frozenset({"1"}), strategies=[a],
                          telegram_enqueue=lambda con, sid, et, chat, text, now_ms: queued.append((sid, et, chat)))
    assert again.strategies["fake_a"].new_signals == [] and again.strategies["fake_a"].new_updates == 0 and queued == []
    assert a.scans[-1] == (through, through)
    assert len(read_signals(root, "fake_a")) == 3


def test_stale_data_means_no_strategy_is_asked(env):
    app, fcfg, config_dir = env
    a = Fake("fake_a", [T0 + 3 * DAY + 15 * MIN])
    out = run_live_tick(app, fcfg, LiveConfig(), config_dir, now=from_ms(LAST_1M + 20 * MIN), downloader=_downloader(app), strategies=[a])
    assert out.status == "stale" and a.scans == [] and out.strategies == {}
    assert not (app.data.data_dir / "signals" / "fake_a").exists()


def test_a_failing_strategy_keeps_its_cursor_the_others_carry_on(env):
    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    ok, bad = Fake("fake_ok", [T0 + 3 * DAY + 15 * MIN]), Fake("fake_bad", [], fail=True)
    out = run_live_tick(app, fcfg, LiveConfig(), config_dir, now=now, downloader=_downloader(app), strategies=[bad, ok])
    assert out.status == "error" and "boom" in out.detail
    assert len(read_signals(app.data.data_dir / "signals", "fake_ok")) == 1
    cursors = json.loads((app.data.data_dir / "paper" / "strategies_cursor.json").read_text(encoding="utf-8"))
    assert "fake_bad" not in cursors and "fake_ok" in cursors


def test_no_alerts_without_chats_or_when_disabled(env):
    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    queued = []
    put = lambda con, sid, et, chat, text, now_ms: queued.append(et)  # noqa: E731
    run_live_tick(app, fcfg, LiveConfig(), config_dir, now=now, downloader=_downloader(app), strategies=[Fake("x", [LAST_1M + MIN - 14 * MIN])], telegram_enqueue=put)
    off = LiveConfig.model_validate({"telegram": {"enabled": False}})
    run_live_tick(app, fcfg, off, config_dir, now=now, downloader=_downloader(app), chat_ids=frozenset({"1"}),
                  strategies=[Fake("y", [LAST_1M + MIN - 14 * MIN])], telegram_enqueue=put)
    assert queued == []
