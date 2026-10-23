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


def test_new_signal_alert_shows_the_strategy_record_not_a_confidence(env):
    """A new-signal alert carries the strategy's closed paper record (the alerted signal itself excluded) instead of the
    unvalidated per-signal confidence; the strategy's new signals still come before its updates."""
    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    through = (LAST_1M + MIN) // (15 * MIN) * (15 * MIN)
    fwd = T0 + 3 * DAY
    a = Fake("fake_a", [fwd + 15 * MIN, through - 60 * MIN, through])
    sent = []
    run_live_tick(app, fcfg, LiveConfig(alert_recency_hours=2), config_dir, now=now, downloader=_downloader(app), chat_ids=frozenset({"1"}),
                  strategies=[a], telegram_enqueue=lambda con, sid, et, chat, text, now_ms: sent.append((et.split(":")[0], text)))
    assert [k for k, _ in sent] == ["new_signal", "new_signal", "update"]
    since = from_ms(fwd).strftime("%Y-%m-%d")
    # the signal at through - 60 min closes itself later; only the first signal counts for it
    assert f"Record (paper since {since}): 1 closed, win 0%, net -1.00 R" in sent[0][1]
    assert f"Record (paper since {since}): 2 closed, win 0%, net -2.00 R" in sent[1][1]
    for _, text in sent[:2]:
        assert "Confidence" not in text and "Quality: no validated per-signal estimate" in text


@pytest.mark.parametrize("charts", [True, False])
def test_every_alert_gets_its_picture_unless_switched_off(env, charts):
    """docs/FEATURES_PLAN.md H5: one picture per queued alert (same signal_id and event type as the outbox entry);
    ``telegram.charts: false`` draws none. The pictures themselves are tested in tests/telegram/test_chart.py."""
    from arven.core.live_config import LiveTelegramConfig
    from arven.telegram.outbox import charts_dir, load_chart

    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    through = (LAST_1M + MIN) // (15 * MIN) * (15 * MIN)
    a = Fake("fake_a", [T0 + 3 * DAY + 15 * MIN, through - 60 * MIN, through])
    queued = []
    live = LiveConfig(alert_recency_hours=2, telegram=LiveTelegramConfig(charts=charts))
    out = run_live_tick(app, fcfg, live, config_dir, now=now, downloader=_downloader(app), chat_ids=frozenset({"1"}), strategies=[a],
                        telegram_enqueue=lambda con, sid, et, chat, text, now_ms: queued.append((sid, et)))
    assert len(queued) == 3 and out.chart_errors == []
    pictures = [load_chart(charts_dir(app.data.data_dir), sid, et) for sid, et in queued]
    if charts:
        assert out.charts == 3 and all(p is not None and p.startswith(b"\x89PNG") for p in pictures)
    else:
        assert out.charts == 0 and all(p is None for p in pictures)


def test_alerts_are_queued_in_the_configured_language(env):
    from arven.core.live_config import LiveTelegramConfig

    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    through = (LAST_1M + MIN) // (15 * MIN) * (15 * MIN)
    a = Fake("fake_a", [T0 + 3 * DAY + 15 * MIN, through - 60 * MIN, through])
    texts = []
    live = LiveConfig(alert_recency_hours=2, telegram=LiveTelegramConfig(language="ru", charts=False))
    run_live_tick(app, fcfg, live, config_dir, now=now, downloader=_downloader(app), chat_ids=frozenset({"1"}), strategies=[a],
                  telegram_enqueue=lambda con, sid, et, chat, text, now_ms: texts.append(text))
    assert [t.split("\n")[0].split(" [")[0].split(":")[0] for t in texts] == ["НОВЫЙ СИГНАЛ", "НОВЫЙ СИГНАЛ", "Закрыто"]
    assert "Позиция закрыта по стопу" in texts[2]


class OpenFake(Fake):
    """A fake whose signals stay open, with a side and a timeframe (for the conflict check)."""

    def __init__(self, sid: str, times: list[int], side: int, tf: str):
        super().__init__(sid, times)
        self.side, self.tf = side, tf

    def scan(self, ctx, after, through, stored):
        out = []
        for s in super().scan(ctx, after, through, stored):
            if self.side == -1:
                s = EngineSignal(symbol="BTCUSDT", side=-1, strategy_id=s.strategy_id, strategy_version="v1", grade=Grade.EXPERIMENTAL,
                                 event_time_ms=s.event_time_ms, entry_reference=100.0, stop=101.0, tp_ladder=(TPLevel(1.0, 1.0, 99.0),),
                                 risk_fraction=0.01, confidence=0.5, regime="n/a", reasons=("fake",), risk_checks=(), versions=SignalVersions("v", "h", None))
            out.append(s)
        return out

    def resolve(self, ctx, s):
        return LiveOutcome(s, (), "open")


def test_a_signal_against_another_strategys_open_signal_is_marked_do_not_enter(env):
    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    through = (LAST_1M + MIN) // (15 * MIN) * (15 * MIN)
    long_4h = OpenFake("long_4h", [through - 60 * MIN], 1, "4h")
    long_1h = OpenFake("long_1h", [through - 30 * MIN], 1, "1h")
    short_15m = OpenFake("short_15m", [through], -1, "15m")
    texts: dict[str, str] = {}
    run_live_tick(app, fcfg, LiveConfig(alert_recency_hours=2), config_dir, now=now, downloader=_downloader(app), chat_ids=frozenset({"1"}),
                  strategies=[short_15m, long_1h, long_4h], telegram_enqueue=lambda con, sid, et, chat, text, now_ms: texts.__setitem__(sid, text))
    root = app.data.data_dir / "signals"
    short_id = read_signals(root, "short_15m")[0].signal_id
    assert texts[short_id].startswith("DO NOT ENTER - contradicts an active signal: long_4h (4h, LONG since")
    assert "long_1h (1h, LONG" in texts[short_id].split("\n\n")[0] and "recorded for the statistics only" in texts[short_id]
    assert texts[read_signals(root, "long_1h")[0].signal_id].startswith("Confirms: long_4h (4h, LONG")
    assert not texts[read_signals(root, "long_4h")[0].signal_id].startswith(("DO NOT", "Confirms"))  # the first one stands alone
    assert [len(read_signals(root, s)) for s in ("short_15m", "long_1h", "long_4h")] == [1, 1, 1]  # records unchanged
    log = [json.loads(x) for x in (app.data.data_dir / "paper" / "conflicts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {x["strategy"] for x in log} == {"short_15m", "long_1h"} and next(x for x in log if x["strategy"] == "short_15m")["mode"] == "block"


def test_conflict_mode_off_leaves_the_alerts_as_they_were(env):
    app, fcfg, config_dir = env
    now = from_ms(LAST_1M + MIN + 30_000)
    through = (LAST_1M + MIN) // (15 * MIN) * (15 * MIN)
    texts: list[str] = []
    run_live_tick(app, fcfg, LiveConfig(alert_recency_hours=2, conflict_mode="off"), config_dir, now=now, downloader=_downloader(app),
                  chat_ids=frozenset({"1"}), strategies=[OpenFake("a", [through], -1, "15m"), OpenFake("b", [through - 60 * MIN], 1, "4h")],
                  telegram_enqueue=lambda con, sid, et, chat, text, now_ms: texts.append(text))
    assert len(texts) == 2 and not any(t.startswith(("DO NOT", "Confirms", "Contradicts")) for t in texts)
    assert not (app.data.data_dir / "paper" / "conflicts.jsonl").exists()
