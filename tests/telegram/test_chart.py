"""Alert pictures (docs/FEATURES_PLAN.md H5): drawing, no look-ahead, the same prices as the text, and the photo send
with its text fallback against a scripted fake Telegram server (no sockets)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from arven.core.telegram_config import TelegramConfig
from arven.core.time import from_ms
from arven.data.storage.db import connect
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.telegram.chart import HEIGHT, WIDTH, candles_until, level_labels, render_signal_chart
from arven.telegram.client import CAPTION_LIMIT, send_photo
from arven.telegram.messages import chart_title, format_new_signal
from arven.telegram.outbox import chart_path, enqueue, get_entry, load_chart, save_chart
from arven.telegram.runs import run_telegram_send_tick

from test_client import ScriptedOpener, http_error, ok_response
from test_messages import make_signal

M15 = 15 * 60_000
T0 = 1_782_864_000_000  # 2026-07-01 00:00 UTC
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _bars(n: int = 200, seed: int = 3):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = np.concatenate([[100.0], c[:-1]])
    h, lo = np.maximum(o, c) + 0.2, np.minimum(o, c) - 0.2
    return T0 + np.arange(n) * M15, o, h, lo, c


def _signal_at(i: int, **over):
    """A LONG at the close of bar ``i`` (entry 100, stop 98, TPs 102 / 104 from make_signal)."""
    return make_signal(event_time_ms=T0 + (i + 1) * M15, **over)


def _candles(cutoff: int):
    t, o, h, lo, c = _bars()
    return candles_until(t, M15, o, h, lo, c, cutoff, "15m")


def test_candles_until_takes_only_bars_closed_by_the_cutoff_and_skips_missing_ones():
    t, o, h, lo, c = _bars()
    c = c.copy()
    c[50] = np.nan  # a missing bar
    cut = int(t[60]) + M15  # the close of bar 60
    got = candles_until(t, M15, o, h, lo, c, cut, "15m")
    assert got.close_ms[-1] == cut and got.open_time_ms[-1] == t[60]
    assert not np.isin(t[50], got.open_time_ms)
    assert len(candles_until(t, M15, o, h, lo, c, cut - 1, "15m").close_ms) and candles_until(t, M15, o, h, lo, c, cut - 1, "15m").close_ms[-1] == cut - M15
    assert len(candles_until(t, M15, o, h, lo, c, cut, "15m", limit=10).close) == 10


def test_picture_never_depends_on_bars_after_the_signal():
    """No look-ahead: the picture of a signal is the same whatever happened after it."""
    t, o, h, lo, c = _bars()
    s = _signal_at(80)
    later = c.copy()
    later[81:] += 50.0  # a wild move after the signal
    a = render_signal_chart(s, candles_until(t, M15, o, h, lo, c, s.event_time_ms, "15m"), chart_title(s))
    b = render_signal_chart(s, candles_until(t, M15, o, np.maximum(h, later), lo, later, s.event_time_ms, "15m"), chart_title(s))
    assert a == b


def test_render_gives_a_small_deterministic_png_of_the_right_size():
    s = _signal_at(120)
    png = render_signal_chart(s, _candles(s.event_time_ms), chart_title(s))
    assert png.startswith(PNG_MAGIC) and len(png) < 1_000_000
    assert Image.open(io.BytesIO(png)).size == (WIDTH, HEIGHT)
    assert png == render_signal_chart(s, _candles(s.event_time_ms), chart_title(s))


def test_the_picture_shows_the_same_prices_as_the_text():
    s = _signal_at(120)
    text = format_new_signal(s)
    labels = level_labels(s)
    assert [lbl for lbl, _, _ in labels] == ["ENTRY 100.00", "STOP 98.00", "TP1 102.00", "TP2 104.00"]
    for label, price, _ in labels:
        assert label.split(" ")[1] == f"{price:.2f}" and f"{price:.2f}" in text


def test_an_update_picture_marks_the_event():
    s = _signal_at(120)
    u = SignalUpdate(s.signal_id, s.event_time_ms + 5 * M15, SignalUpdateKind.TP_HIT, "TP1")
    png = render_signal_chart(s, _candles(u.time_ms), chart_title(s, u), update=u, update_label="TP hit")
    assert png.startswith(PNG_MAGIC) and png != render_signal_chart(s, _candles(u.time_ms), chart_title(s))
    assert chart_title(s, u).startswith("TP hit: ")


def test_nothing_is_drawn_on_missing_or_stale_candles():
    s = _signal_at(120)
    with pytest.raises(ValueError, match="no closed candles"):
        render_signal_chart(s, _candles(T0), chart_title(s))
    stale = _signal_at(120 + 4 * 24 + 1)  # a day and a bar after the newest candle we pass
    with pytest.raises(ValueError, match="stale"):
        render_signal_chart(stale, _candles(_signal_at(120).event_time_ms), chart_title(stale))


def test_saved_pictures_are_found_by_signal_and_event(tmp_path):
    save_chart(tmp_path, "sig1", "new_signal", PNG_MAGIC + b"x")
    assert load_chart(tmp_path, "sig1", "new_signal") == PNG_MAGIC + b"x"
    assert load_chart(tmp_path, "sig1", "update:TP_HIT:abc") is None
    assert load_chart(None, "sig1", "new_signal") is None
    assert chart_path(tmp_path, "sig1", "new_signal").suffix == ".png"


# --- sending: sendPhoto with the text as caption, text fallback ------------------------------------------------------


def _cfg() -> TelegramConfig:
    return TelegramConfig.model_validate({"dry_run": False, "command_poll_timeout_seconds": 0, "max_send_attempts": 2})


def test_send_photo_uploads_the_png_with_the_caption():
    opener = ScriptedOpener(ok_response({"message_id": 9}))
    png = PNG_MAGIC + b"picture"
    sent = send_photo("123", png, "caption text", token="t", opener=opener, sleep=lambda s: None)
    req = opener.calls[0]
    assert sent.message_id == 9 and req.full_url.endswith("/sendPhoto")
    assert req.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert png in req.data and b"caption text" in req.data and b'name="chat_id"\r\n\r\n123' in req.data


def test_an_entry_with_a_picture_goes_out_as_a_photo(tmp_path):
    con = connect(":memory:")
    oid = enqueue(con, signal_id="s1", event_type="new_signal", chat_id="1", text="alert", now_ms=1000)
    save_chart(tmp_path, "s1", "new_signal", PNG_MAGIC + b"p")
    opener = ScriptedOpener(ok_response({"message_id": 5}))
    summary = run_telegram_send_tick(con, _cfg(), token="t", opener=opener, sleep=lambda s: None, now=from_ms(2000), charts_root=tmp_path)
    assert summary.sent == 1 and summary.photos == 1 and summary.ok
    assert [r.full_url.rsplit("/", 1)[1] for r in opener.calls] == ["sendPhoto"]
    assert get_entry(con, oid).telegram_message_id == 5


def test_a_failed_picture_falls_back_to_the_text(tmp_path):
    con = connect(":memory:")
    oid = enqueue(con, signal_id="s1", event_type="new_signal", chat_id="1", text="alert", now_ms=1000)
    save_chart(tmp_path, "s1", "new_signal", PNG_MAGIC + b"p")
    opener = ScriptedOpener(http_error(400), ok_response({"message_id": 6}))
    summary = run_telegram_send_tick(con, _cfg(), token="t", opener=opener, sleep=lambda s: None, now=from_ms(2000), charts_root=tmp_path)
    assert summary.sent == 1 and summary.photos == 0 and len(summary.photo_fallbacks) == 1 and summary.ok
    assert [r.full_url.rsplit("/", 1)[1] for r in opener.calls] == ["sendPhoto", "sendMessage"]
    assert get_entry(con, oid).status == "sent" and get_entry(con, oid).telegram_message_id == 6


def test_text_too_long_for_a_caption_and_entries_without_a_picture_go_as_text(tmp_path):
    con = connect(":memory:")
    enqueue(con, signal_id="s1", event_type="new_signal", chat_id="1", text="x" * (CAPTION_LIMIT + 1), now_ms=1000)
    enqueue(con, signal_id="s2", event_type="new_signal", chat_id="1", text="no picture", now_ms=2000)
    save_chart(tmp_path, "s1", "new_signal", PNG_MAGIC + b"p")
    opener = ScriptedOpener(ok_response({"message_id": 1}), ok_response({"message_id": 2}))
    summary = run_telegram_send_tick(con, _cfg(), token="t", opener=opener, sleep=lambda s: None, now=from_ms(3000), charts_root=tmp_path)
    assert summary.sent == 2 and summary.photos == 0
    assert [r.full_url.rsplit("/", 1)[1] for r in opener.calls] == ["sendMessage", "sendMessage"]


def test_a_real_alert_text_fits_in_a_caption():
    s = make_signal(reasons=("a" * 80, "b" * 80, "c" * 80))
    assert len(format_new_signal(s)) <= CAPTION_LIMIT


def test_update_label_names_the_exit_reason():
    from arven.telegram.messages import update_label

    assert update_label(SignalUpdate("s", 0, SignalUpdateKind.CLOSED, "reason=STOP;fraction=1.00000000")) == "Closed: STOP"
    assert update_label(SignalUpdate("s", 0, SignalUpdateKind.TP_HIT, "TP1")) == "TP hit"
