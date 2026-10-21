"""A signal as a picture for Telegram (docs/FEATURES_PLAN.md H5): 15m candles up to the signal (or the update), the
entry, stop and take-profit levels with their prices, the risk / reward areas and a caption. Pure: arrays in, PNG bytes
out - no I/O, no clock. Drawn with Pillow (already installed with streamlit; no plotting library needed).

No look-ahead: only candles that had *closed* by the cut-off time are drawn (``candles_until``), so the picture of a new
signal shows exactly what was known when it was announced. The level prices are formatted by ``level_labels``, the
same ``.2f`` the alert text uses, so the picture and the text always show the same numbers.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from arven.core.time import from_ms
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate

WIDTH, HEIGHT = 1000, 620
LEFT, RIGHT, TOP, BOTTOM = 64, 150, 78, 56  # plot margins (the right one holds the level labels)
MAX_CANDLES = 96  # one day of 15m candles
MAX_GAP_MS = 24 * 3_600_000  # a signal more than a day after the newest candle is drawn on stale data: refused
COLORS = {
    "bg": (15, 20, 25), "grid": (34, 42, 51), "text": (214, 221, 230), "faint": (138, 150, 163),
    "up": (38, 166, 154), "down": (239, 83, 80), "entry": (74, 163, 255), "stop": (239, 83, 80), "tp": (38, 166, 154),
    "event": (255, 193, 7),
}


@dataclass(frozen=True, slots=True)
class Candles:
    """Closed candles of one timeframe, oldest first (``close_ms`` = open time + bar length)."""

    open_time_ms: np.ndarray
    close_ms: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    label: str  # e.g. "15m"


def candles_until(open_time_ms: np.ndarray, tf_ms: int, o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray,
                  cutoff_ms: int, label: str, limit: int = MAX_CANDLES) -> Candles:
    """The last ``limit`` complete candles whose close is at or before ``cutoff_ms`` (missing bars, NaN, skipped)."""
    close_ms = open_time_ms + tf_ms
    keep = (close_ms <= cutoff_ms) & np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & np.isfinite(c)
    idx = np.flatnonzero(keep)[-limit:]
    return Candles(open_time_ms[idx], close_ms[idx], o[idx], h[idx], lo[idx], c[idx], label)


def level_labels(signal: EngineSignal) -> list[tuple[str, float, str]]:
    """(label, price, colour key) of every level drawn - entry, stop, each take-profit - with the alert text's ``.2f``."""
    entry = "LIMIT" if signal.entry_type == "limit" else "ENTRY"
    out = [(f"{entry} {signal.entry_reference:.2f}", signal.entry_reference, "entry"), (f"STOP {signal.stop:.2f}", signal.stop, "stop")]
    out += [(f"TP{i + 1} {lvl.price:.2f}", lvl.price, "tp") for i, lvl in enumerate(signal.tp_ladder)]
    return out


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _spread_labels(ys: list[float], top: float, bottom: float, gap: float) -> list[float]:
    """Label y positions in the same order, at least ``gap`` apart and inside [top, bottom]."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    placed = [0.0] * len(ys)
    last = top - gap
    for i in order:
        placed[i] = max(ys[i], last + gap)
        last = placed[i]
    overflow = last - bottom
    if overflow > 0:  # shift the whole stack up, never above the top
        for i in order:
            placed[i] = max(top, placed[i] - overflow)
    return placed


def render_signal_chart(signal: EngineSignal, candles: Candles, title: str, *, update: SignalUpdate | None = None,
                        update_label: str | None = None) -> bytes:
    """PNG bytes of the signal (or of one of its updates: ``update`` marks its time and ``update_label`` names it)."""
    if len(candles.close) == 0:
        raise ValueError("no closed candles before the cut-off - nothing to draw")
    if signal.event_time_ms - int(candles.close_ms[-1]) > MAX_GAP_MS:
        raise ValueError("the newest candle is more than a day older than the signal - stale data, not drawn")
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["bg"])
    draw = ImageDraw.Draw(img, "RGBA")
    x0, x1, y0, y1 = LEFT, WIDTH - RIGHT, TOP, HEIGHT - BOTTOM
    levels = level_labels(signal)
    lo_p = float(min(candles.low.min(), *(p for _, p, _ in levels)))
    hi_p = float(max(candles.high.max(), *(p for _, p, _ in levels)))
    pad = (hi_p - lo_p) * 0.06 or max(abs(hi_p) * 1e-3, 1e-6)
    lo_p, hi_p = lo_p - pad, hi_p + pad

    def y(price: float) -> float:
        return y1 - (price - lo_p) / (hi_p - lo_p) * (y1 - y0)

    n = len(candles.close)
    slot = (x1 - x0) / (n + 14)  # room on the right of the last candle for the level areas
    body = max(1.0, slot * 0.62)

    def x(i: float) -> float:
        return x0 + (i + 0.5) * slot

    small, mid, big = _font(13), _font(15), _font(20)
    # grid and price ticks (left)
    for k in range(6):
        p = lo_p + (hi_p - lo_p) * k / 5
        yy = y(p)
        draw.line([(x0, yy), (x1, yy)], fill=COLORS["grid"], width=1)
        draw.text((6, yy - 7), f"{p:.2f}", font=small, fill=COLORS["faint"])
    # time ticks (bottom)
    for i in np.linspace(0, n - 1, 4).round().astype(int):
        xx = x(int(i))
        draw.line([(xx, y0), (xx, y1)], fill=COLORS["grid"], width=1)
        draw.text((xx - 34, y1 + 6), from_ms(int(candles.close_ms[i])).strftime("%m-%d %H:%M"), font=small, fill=COLORS["faint"])

    # risk / reward areas from the signal candle to the right edge
    sig_i = int(np.searchsorted(candles.close_ms, signal.event_time_ms, side="right")) - 1
    sx = x(max(sig_i, 0))
    if signal.tp_ladder:
        far_tp = max(signal.tp_ladder, key=lambda lv: abs(lv.price - signal.entry_reference)).price
        draw.rectangle([sx, min(y(signal.entry_reference), y(far_tp)), x1, max(y(signal.entry_reference), y(far_tp))], fill=(*COLORS["tp"], 34))
    draw.rectangle([sx, min(y(signal.entry_reference), y(signal.stop)), x1, max(y(signal.entry_reference), y(signal.stop))], fill=(*COLORS["stop"], 40))

    # candles
    for i in range(n):
        o, h, lo, c = (float(a[i]) for a in (candles.open, candles.high, candles.low, candles.close))
        col = COLORS["up"] if c >= o else COLORS["down"]
        xx = x(i)
        draw.line([(xx, y(h)), (xx, y(lo))], fill=col, width=1)
        top_b, bot_b = min(y(o), y(c)), max(y(o), y(c))
        draw.rectangle([xx - body / 2, top_b, xx + body / 2, max(bot_b, top_b + 1)], fill=col)

    # signal time and (optionally) the update time
    for yy in range(int(y0), int(y1), 8):
        draw.line([(sx, yy), (sx, yy + 4)], fill=COLORS["faint"], width=1)
    draw.text((sx + 4, y0 + 2), "signal", font=small, fill=COLORS["faint"])
    if update is not None:
        ui = int(np.searchsorted(candles.close_ms, update.time_ms, side="right")) - 1
        ux = x(min(max(ui, 0), n - 1)) + slot / 2
        for yy in range(int(y0), int(y1), 8):
            draw.line([(ux, yy), (ux, yy + 4)], fill=COLORS["event"], width=2)
        draw.text((ux + 4, y0 + 18), update_label or update.kind.value, font=small, fill=COLORS["event"])

    # level lines and their labels on the right
    ys = [y(p) for _, p, _ in levels]
    for (label, _, key), yy in zip(levels, ys, strict=True):
        col = COLORS[key]
        if key == "tp":
            for xx in range(int(sx), int(x1), 10):
                draw.line([(xx, yy), (xx + 6, yy)], fill=col, width=2)
        else:
            draw.line([(sx, yy), (x1, yy)], fill=col, width=2)
    for (label, _, key), ly in zip(levels, _spread_labels(ys, y0, y1 - 18, 20), strict=True):
        draw.rectangle([x1 + 6, ly - 9, WIDTH - 6, ly + 9], fill=(*COLORS[key], 210))
        draw.text((x1 + 11, ly - 8), label, font=mid, fill=(255, 255, 255))

    # caption
    draw.text((LEFT, 14), title, font=big, fill=COLORS["text"])
    sub = f"{candles.label} candles to {from_ms(int(candles.close_ms[-1])).strftime('%Y-%m-%d %H:%M')} UTC  ·  paper signal, not an order"
    draw.text((LEFT, 44), sub, font=small, fill=COLORS["faint"])
    draw.text((LEFT, HEIGHT - 22), "ARVEN decision support - simulated, not financial advice", font=small, fill=COLORS["faint"])

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


__all__ = ["Candles", "candles_until", "level_labels", "render_signal_chart"]
