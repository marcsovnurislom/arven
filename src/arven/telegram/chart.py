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
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from arven.core.prices import fmt_price
from arven.core.time import from_ms
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate
from arven.telegram.ru import CHART as WORDS

WIDTH, HEIGHT = 1000, 620
LEFT, RIGHT, TOP, BOTTOM = 64, 150, 78, 56  # plot margins (the right one holds the level labels)
MAX_CANDLES = 96  # one day of 15m candles
MAX_CANDLES_WITH_OVERLAY = 240  # a strategy's drawing (e.g. S7's trend line) may need a longer window to be seen
MAX_GAP_MS = 24 * 3_600_000  # a signal more than a day after the newest candle is drawn on stale data: refused
COLORS = {
    "bg": (15, 20, 25), "grid": (34, 42, 51), "text": (214, 221, 230), "faint": (138, 150, 163),
    "up": (38, 166, 154), "down": (239, 83, 80), "entry": (74, 163, 255), "stop": (239, 83, 80), "tp": (38, 166, 154),
    "event": (255, 193, 7), "line": (186, 104, 200), "zone": (74, 163, 255), "fib": (138, 150, 163),
}


@dataclass(frozen=True, slots=True)
class ChartOverlay:
    """A strategy's own drawing on top of the candles, in prices and bar *close* times (already computed by the strategy;
    nothing here is derived from prices). S7: the broken trend line, its touches, fib 0 / 0.5 / 1 and the entry zone."""

    lines: tuple[tuple[int, float, int, float, str], ...] = ()  # (t0, p0, t1, p1, label): a straight segment
    points: tuple[tuple[int, float], ...] = ()  # (t, price): marked candles, e.g. the line's touches
    levels: tuple[tuple[float, str], ...] = ()  # (price, label): faint horizontal reference levels
    zone: tuple[float, float, str] | None = None  # (low, high, label): a price band ...
    zone_from_ms: int | None = None  # ... drawn from this close time on (None: across the whole window)
    start_ms: int | None = None  # the earliest time the drawing needs on screen (the window is widened to it)

    def prices(self) -> list[float]:
        out = [p for ln in self.lines for p in (ln[1], ln[3])] + [p for _, p in self.points] + [p for p, _ in self.levels]
        return out + ([self.zone[0], self.zone[1]] if self.zone else [])


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
                  cutoff_ms: int, label: str, limit: int = MAX_CANDLES, since_ms: int | None = None) -> Candles:
    """The last ``limit`` complete candles whose close is at or before ``cutoff_ms`` (missing bars, NaN, skipped).
    ``since_ms``: widen the window back to this close time (plus a little room), up to ``MAX_CANDLES_WITH_OVERLAY``."""
    close_ms = open_time_ms + tf_ms
    keep = (close_ms <= cutoff_ms) & np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & np.isfinite(c)
    idx = np.flatnonzero(keep)
    if since_ms is not None:
        need = int(np.count_nonzero(close_ms[idx] >= since_ms)) + 8
        limit = min(max(limit, need), MAX_CANDLES_WITH_OVERLAY)
    idx = idx[-limit:]
    return Candles(open_time_ms[idx], close_ms[idx], o[idx], h[idx], lo[idx], c[idx], label)


def level_labels(signal: EngineSignal, lang: str = "en") -> list[tuple[str, float, str]]:
    """(label, price, colour key) of every level drawn - entry, stop, each take-profit - with the alert text's ``.2f``."""
    w = WORDS[lang]
    entry = w["limit"] if signal.entry_type == "limit" else w["entry"]
    out = [(f"{entry} {fmt_price(signal.entry_reference)}", signal.entry_reference, "entry"),
           (f"{w['stop']} {fmt_price(signal.stop, signal.entry_reference)}", signal.stop, "stop")]
    out += [(f"TP{i + 1} {fmt_price(lvl.price, signal.entry_reference)}", lvl.price, "tp") for i, lvl in enumerate(signal.tp_ladder)]
    return out


# Pillow's built-in font (Aileron) has no Cyrillic: Russian words need a system font that has it. The first one found
# is used; with none, the picture stays in English (the alert text under it is Russian either way).
CYRILLIC_FONTS = ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf", "segoeui.ttf",
                  "LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")


@lru_cache(maxsize=1)
def cyrillic_font() -> str | None:
    for name in CYRILLIC_FONTS:
        try:
            ImageFont.truetype(name, 12)
        except OSError:
            continue
        return name
    return None


def chart_language(lang: str) -> str:
    """The language the picture can actually be drawn in: Russian only with a Cyrillic font installed."""
    return "ru" if lang == "ru" and cyrillic_font() is not None else "en"


def _font(size: int, lang: str = "en") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = cyrillic_font() if lang == "ru" else None
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


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


def _x_index(candles: Candles, t_ms: int) -> float:
    """A close time as a (fractional) candle index; times between two candles fall in between."""
    t = candles.close_ms.astype(float)
    return float(np.interp(t_ms, t, np.arange(len(t), dtype=float), left=-1.0, right=len(t) - 1.0))


def _clip_segment(candles: Candles, ln: tuple[int, float, int, float, str]) -> tuple[float, float, float, float] | None:
    """The part of a line segment inside the drawn window, as (i0, p0, i1, p1) in candle indices."""
    t0, p0, t1, p1, _ = ln
    first, last = int(candles.close_ms[0]), int(candles.close_ms[-1])
    if t1 < first or t0 > last or t1 <= t0:
        return None
    at = lambda t: p0 + (p1 - p0) * (t - t0) / (t1 - t0)  # noqa: E731
    a, b = max(t0, first), min(t1, last)
    return _x_index(candles, a), at(a), _x_index(candles, b), at(b)


def _visible_overlay_prices(overlay: ChartOverlay | None, candles: Candles) -> list[float]:
    if overlay is None:
        return []
    out = [p for t, p in overlay.points if candles.close_ms[0] <= t <= candles.close_ms[-1]] + [p for p, _ in overlay.levels]
    for ln in overlay.lines:
        seg = _clip_segment(candles, ln)
        if seg is not None:
            out += [seg[1], seg[3]]
    return out + ([overlay.zone[0], overlay.zone[1]] if overlay.zone else [])


def _label(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, color) -> None:
    """Text on a dark backing, readable over candles."""
    l, t, r, b = draw.textbbox(xy, text, font=font)
    draw.rectangle([l - 2, t - 1, r + 2, b + 1], fill=(*COLORS["bg"], 190))
    draw.text(xy, text, font=font, fill=color)


def _draw_overlay(draw: ImageDraw.ImageDraw, overlay: ChartOverlay, candles: Candles, x, y, slot: float, x0: float, x1: float, font,
                  words: dict[str, str]) -> None:
    if overlay.zone is not None:
        zl, zh, label = overlay.zone
        zs = x(max(_x_index(candles, overlay.zone_from_ms), 0.0)) if overlay.zone_from_ms is not None else x0
        draw.rectangle([zs, y(zh), x1, y(zl)], fill=(*COLORS["zone"], 46), outline=(*COLORS["zone"], 140))
        _label(draw, (zs + 4, y(zh) - 16), words.get(label, label), font, COLORS["zone"])
    for price, label in overlay.levels:
        yy = y(price)
        for xx in range(int(x0), int(x1), 6):
            draw.line([(xx, yy), (xx + 2, yy)], fill=COLORS["fib"], width=1)
        _label(draw, (x0 + 4, yy - 15), label, font, COLORS["fib"])
    for ln in overlay.lines:
        seg = _clip_segment(candles, ln)
        if seg is None:
            continue
        i0, p0, i1, p1 = seg
        draw.line([(x(i0), y(p0)), (x(i1), y(p1))], fill=COLORS["line"], width=3)
        _label(draw, (x(i0) + 6, y(p0) + 4), words.get(ln[4], ln[4]), font, COLORS["line"])
    for t, price in overlay.points:
        i = _x_index(candles, t)
        if 0 <= i <= len(candles.close) - 1:
            r = max(3.0, slot * 0.45)
            draw.ellipse([x(i) - r, y(price) - r, x(i) + r, y(price) + r], outline=COLORS["line"], width=2)


def render_signal_chart(signal: EngineSignal, candles: Candles, title: str, *, update: SignalUpdate | None = None,
                        update_label: str | None = None, overlay: ChartOverlay | None = None, lang: str = "en") -> bytes:
    """PNG bytes of the signal (or of one of its updates: ``update`` marks its time and ``update_label`` names it),
    with the strategy's ``overlay`` drawn under the level lines. ``lang``: the picture's own words (``title`` and
    ``update_label`` come from the caller in the same language; see ``chart_language``)."""
    lang = chart_language(lang)
    words = WORDS[lang]
    if len(candles.close) == 0:
        raise ValueError("no closed candles before the cut-off - nothing to draw")
    if signal.event_time_ms - int(candles.close_ms[-1]) > MAX_GAP_MS:
        raise ValueError("the newest candle is more than a day older than the signal - stale data, not drawn")
    img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["bg"])
    draw = ImageDraw.Draw(img, "RGBA")
    x0, x1, y0, y1 = LEFT, WIDTH - RIGHT, TOP, HEIGHT - BOTTOM
    levels = level_labels(signal, lang)
    extra = [p for _, p, _ in levels] + _visible_overlay_prices(overlay, candles)
    lo_p = float(min(candles.low.min(), *extra))
    hi_p = float(max(candles.high.max(), *extra))
    pad = (hi_p - lo_p) * 0.06 or max(abs(hi_p) * 1e-3, 1e-6)
    lo_p, hi_p = lo_p - pad, hi_p + pad

    def y(price: float) -> float:
        return y1 - (price - lo_p) / (hi_p - lo_p) * (y1 - y0)

    n = len(candles.close)
    slot = (x1 - x0) / (n + 14)  # room on the right of the last candle for the level areas
    body = max(1.0, slot * 0.62)

    def x(i: float) -> float:
        return x0 + (i + 0.5) * slot

    small, mid, big = _font(13, lang), _font(15, lang), _font(20, lang)
    # grid and price ticks (left)
    for k in range(6):
        p = lo_p + (hi_p - lo_p) * k / 5
        yy = y(p)
        draw.line([(x0, yy), (x1, yy)], fill=COLORS["grid"], width=1)
        draw.text((6, yy - 7), fmt_price(p, hi_p), font=small, fill=COLORS["faint"])
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

    if overlay is not None:
        _draw_overlay(draw, overlay, candles, x, y, slot, x0, x1, small, words)

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
    draw.text((sx + 4, y0 + 2), words["signal"], font=small, fill=COLORS["faint"])
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
    sub = words["sub"].format(tf=candles.label, t=from_ms(int(candles.close_ms[-1])).strftime('%Y-%m-%d %H:%M'))
    draw.text((LEFT, 44), sub, font=small, fill=COLORS["faint"])
    draw.text((LEFT, HEIGHT - 22), words["foot"], font=small, fill=COLORS["faint"])

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


__all__ = ["COLORS", "Candles", "ChartOverlay", "candles_until", "chart_language", "cyrillic_font", "level_labels", "render_signal_chart"]
