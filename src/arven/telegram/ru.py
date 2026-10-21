"""Russian wording of the Telegram messages (``config/live.yaml`` ``telegram.language: ru``). Pure text: every number
comes from the signal / update / summary already computed elsewhere (CLAUDE.md rule 9), exactly as the English
formatters in ``arven.telegram.messages`` print it.

The stored signal keeps its English ``reasons`` and update ``detail`` (they are part of its content hash); they are
translated here at display time by fixed patterns, and any text no pattern knows is shown unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from arven.core.time import from_ms
from arven.engine.signal import EngineSignal
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind

DISCLAIMER = "Бумажный сигнал: симуляция, не реальный ордер и не финансовый совет."

UPDATE_VERB = {
    SignalUpdateKind.TP_HIT: "Цель достигнута",
    SignalUpdateKind.STOP_MOVED: "Стоп перенесён",
    SignalUpdateKind.CLOSED: "Закрыто",
    SignalUpdateKind.CANCELLED: "Отменено",
    SignalUpdateKind.FILLED: "Вход исполнен",
}
SIDE = {1: "ПОКУПКА (LONG)", -1: "ПРОДАЖА (SHORT)"}
SIDE_SHORT = {1: "LONG", -1: "SHORT"}
GRADE = {"EXPERIMENTAL": "ЭКСПЕРИМЕНТ", "VALIDATED": "ПРОВЕРЕНА"}
SYMBOL = {"XAUUSDT": "ЗОЛОТО XAUUSD (цены: Binance XAUUSDT)", "BTCUSDT": "BTCUSDT"}
EXIT_REASON = {
    "STOP": "по стопу", "STOP_TRAIL": "по подтянутому стопу", "STOP_BREAKEVEN": "в безубыток",
    "TIME_STOP": "по времени", "TIME": "по времени",
}
CANCEL_REASON = {
    "level1_moved": "уровень 1 сдвинулся (сетап перестроен)",
    "closed_below_level0": "свеча закрылась за уровнем 0",
    "zone_broken_by_impulse": "зону входа пробил импульс",
    "expired": "лимитный ордер не исполнился за отведённое время",
    "no_data": "нет данных",
}
ZONE = {"fvg": "FVG", "ifvg": "iFVG", "level": "уровень", "order_block": "ордер-блок", "none": "нет"}
VERDICT = {
    "too_few": "слишком мало закрытых сигналов для вывода",
    "losing": "УБЫТОЧНА: 95 % интервал среднего R ниже 0",
    "inconclusive": "неясно: 95 % интервал содержит 0",
    "positive": "пока в плюсе (95 % интервал выше 0), но ещё не доказано",
}
SYSTEM_TITLE = {
    "repeated errors": "повторяющиеся ошибки", "market data stale": "данные рынка устарели",
    "daily backup failed": "не удалась ежедневная резервная копия", "live loop started": "live-цикл запущен",
}

_N = r"([-+]?\d+(?:\.\d+)?)"
_DIRECTION = {"impulse": "импульса", "breakout": "пробоя", "the trade": "сделки"}

# (pattern, replacement) for every reason template the strategies write; checked in order, first full match wins
REASONS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"impulse (bullish|bearish) size=" + _N),
     lambda m: f"импульс {'вверх' if m[1] == 'bullish' else 'вниз'}, размер {m[2]}"),
    (re.compile(r"zone=\[" + _N + "," + _N + r"\] overlap=" + _N + "%"),
     lambda m: f"зона [{m[1]}; {m[2]}], перекрытие {m[3]}%"),
    (re.compile(r"(\d+)h ema_slope_(\d+) agrees with (impulse|breakout|the trade) direction"),
     lambda m: f"наклон EMA{m[2]} на {m[1]}h совпадает с направлением {_DIRECTION[m[3]]}"),
    (re.compile(r"squeeze range \[" + _N + "," + _N + r"\] width=" + _N + " ATR"),
     lambda m: f"сжатие в диапазоне [{m[1]}; {m[2]}], ширина {m[3]} ATR"),
    (re.compile(r"pullback to (\d+)h EMA(\d+) \(" + _N + r"\) held, bounce on (\d+)m"),
     lambda m: f"откат к EMA{m[2]} на {m[1]}h ({m[3]}) удержался, отскок на {m[4]}m"),
    (re.compile(r"(\d+m) trend line broken, fib retest setup armed \(level 0 " + _N + ", level 1 " + _N + r"\)"),
     lambda m: f"{m[1]}: линия тренда пробита, ждём отката по Фибоначчи (уровень 0 {m[2]}, уровень 1 {m[3]})"),
    (re.compile(r"entry: limit " + _N + r" \(fib 0\.5\); cancelled if a (\d+m) bar closes beyond level 0 or above level 1, "
                r"expires if unfilled"),
     lambda m: (f"вход: лимит {m[1]} (fib 0.5); отмена, если свеча {m[2]} закроется за уровнем 0 или выше уровня 1; "
                "ордер истекает, если не исполнится")),
    (re.compile(r"confluence zones: (.+)"),
     lambda m: "зоны совпадения: " + ", ".join(ZONE.get(z.strip(), z.strip()) for z in m[1].split(","))),
    (re.compile(r"funding z-score " + _N + " <= " + _N + " and open-interest z-score " + _N + " >= " + _N + r" \(crowded shorts\)"),
     lambda m: f"z-оценка фандинга {m[1]} ≤ {m[2]}, z-оценка открытого интереса {m[3]} ≥ {m[4]} (перегруженные шорты)"),
    (re.compile(r"market buy now; stop " + _N + "% below the fill; no take-profit"),
     lambda m: f"покупка по рынку сейчас; стоп на {m[1]}% ниже входа; без тейк-профита"),
    (re.compile(r"exit (\d+) h after the last qualifying signal \(a repeat signal extends the hold\)"),
     lambda m: f"выход через {m[1]} ч после последнего подходящего сигнала (повторный сигнал продлевает удержание)"),
)


def reason(text: str) -> str:
    for pattern, render in REASONS:
        m = pattern.fullmatch(text)
        if m:
            return render(m)
    return text


def _fields(detail: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in detail.split(";") if "=" in p)


def _price(x: str) -> str:
    try:
        return f"{float(x):.2f}"
    except ValueError:
        return x


def pct(x: float, digits: int = 0) -> str:
    """A fraction as a Russian-style percentage: 0.5 -> "50 %"."""
    return f"{x * 100:.{digits}f} %"


def _share(x: str) -> str:
    try:
        return pct(float(x))
    except ValueError:
        return x


def update_detail(update: SignalUpdate) -> str:
    """The update's ``detail`` in words (unknown keys and values are kept as they are)."""
    f = _fields(update.detail)
    leg = f" (часть {f['leg']})" if "leg" in f else ""
    if update.kind == SignalUpdateKind.TP_HIT and "price" in f:
        return f"{f.get('level', 'Цель')}: закрыто {_share(f.get('fraction', '1'))} позиции по {_price(f['price'])}{leg}"
    if update.kind == SignalUpdateKind.CLOSED and "reason" in f:
        how = EXIT_REASON.get(f["reason"], f["reason"])
        at = f" по {_price(f['price'])}" if "price" in f else ""
        return f"Позиция закрыта {how}{at}: закрыто {_share(f.get('fraction', '1'))} позиции{leg}"
    if update.kind == SignalUpdateKind.FILLED and "price" in f:
        part = f", доля {f['weight']}" if f.get("weight") not in (None, "1") else ""
        return f"Вход исполнен по {_price(f['price'])}{part}{leg}"
    if update.kind == SignalUpdateKind.STOP_MOVED and "new_stop" in f:
        return f"Новый стоп: {_price(f['new_stop'])}{leg}"
    if update.kind == SignalUpdateKind.CANCELLED and "reason" in f:
        return f"Причина: {CANCEL_REASON.get(f['reason'], f['reason'])}"
    return update.detail


def update_label(update: SignalUpdate) -> str:
    f = _fields(update.detail)
    if update.kind == SignalUpdateKind.CLOSED and "reason" in f:
        return f"Закрыто {EXIT_REASON.get(f['reason'], f['reason'])}"
    if update.kind == SignalUpdateKind.TP_HIT and "level" in f:
        return f"{f['level']} достигнута"
    return UPDATE_VERB[update.kind]


def _utc(ms: int) -> str:
    return from_ms(ms).strftime("%d.%m.%Y %H:%M UTC")


def symbol(sym: str) -> str:
    return SYMBOL.get(sym, sym)


def new_signal(signal: EngineSignal, record_line: str) -> str:
    tp_lines = "\n".join(
        f"  TP{i + 1}: {lvl.price:.2f} ({lvl.r_multiple:.2f}R, закрыть {pct(lvl.close_fraction)})"
        for i, lvl in enumerate(signal.tp_ladder)
    )
    if not signal.tp_ladder and signal.max_holding_minutes is not None:
        tp_lines = f"  Без тейк-профита: выход по времени через {signal.max_holding_minutes / 60:g} ч"
    if signal.entry_type == "limit":
        until = f" (действует до {_utc(signal.valid_until_ms)})" if signal.valid_until_ms else ""
        entry = f"Вход: ЛИМИТ {signal.entry_reference:.2f}{until}"
    else:
        entry = f"Вход (ориентир): {signal.entry_reference:.2f}"
    reasons = "\n".join(f"  • {reason(r)}" for r in signal.reasons[:3]) if signal.reasons else "  (не записаны)"
    regime = "" if signal.regime in ("n/a", "") else f"Режим: {signal.regime}\n"
    return (
        f"НОВЫЙ СИГНАЛ [{GRADE.get(signal.grade.value, signal.grade.value)}]\n"
        f"{symbol(signal.symbol)} {SIDE[signal.side]}\n"
        f"Стратегия: {signal.strategy_id} {signal.strategy_version}, {_utc(signal.event_time_ms)}\n"
        f"{entry}\n"
        f"Стоп: {signal.stop:.2f}\n"
        f"{tp_lines}\n"
        f"Риск: {pct(signal.risk_fraction, 2)} депозита (фиксированное правило, одинаково для всех сигналов)\n"
        "Качество: проверенной оценки отдельного сигнала нет\n"
        f"{record_line}\n"
        f"{regime}"
        f"Почему:\n{reasons}\n\n{DISCLAIMER}"
    )


def record_line(closed: int | None, wins: int, total_r: float, since_ms: int | None) -> str:
    if closed is None or since_ms is None:
        return "Результаты стратегии: нет данных"
    since = from_ms(since_ms).strftime("%d.%m.%Y")
    if closed == 0:
        return f"Результаты стратегии (на бумаге с {since}): закрытых сигналов пока нет"
    return f"Результаты стратегии (на бумаге с {since}): закрыто {closed}, в плюсе {pct(wins / closed)}, итог {total_r:+.2f} R"


def signal_update(signal: EngineSignal, update: SignalUpdate) -> str:
    return (
        f"{UPDATE_VERB[update.kind]}: {symbol(signal.symbol)} {SIDE_SHORT[signal.side]} ({signal.strategy_id}), {_utc(update.time_ms)}\n"
        f"Сигнал от {_utc(signal.event_time_ms)}, вход {signal.entry_reference:.2f}, стоп {signal.stop:.2f}\n"
        f"{update_detail(update)}\n\n{DISCLAIMER}"
    )


def chart_title(signal: EngineSignal, update: SignalUpdate | None = None) -> str:
    head = f"{symbol(signal.symbol)} · {SIDE_SHORT[signal.side]} · {signal.strategy_id} {signal.strategy_version}"
    return head if update is None else f"{update_label(update)}: {head}"


def system_alert(title: str, detail: str) -> str:
    name, _, rest = title.rpartition(": ")
    words = SYSTEM_TITLE.get(rest, rest)
    return f"СИСТЕМНОЕ ПРЕДУПРЕЖДЕНИЕ: {name + ': ' if name else ''}{words}\n{detail}"


def daily_summary(date_label: str, rows: list[tuple[str, str, int, int, float]]) -> str:
    body = "\n".join(f"  {sid} [{GRADE.get(g, g)}]: сигналов {n}, закрыто {c}, итог {r:+.2f}R" for sid, g, n, c, r in rows) or "Сигналов за день не было."
    return f"Итоги дня — {date_label}\n{body}\n\n{DISCLAIMER}"


def weekly_block(sid: str, grade: str, week_closed: int, week_r: float, since: str, n_closed: int, n_open: int, total_r: float,
                 win: str, mean: str, ci: str, dd: str, verdict: str) -> str:
    return (f"{sid} [{GRADE.get(grade, grade)}]\n"
            f"  за неделю: закрыто {week_closed}, {week_r:+.2f}R\n"
            f"  с {since}: закрыто {n_closed} (открыто {n_open}), {total_r:+.2f}R, в плюсе {win} %, "
            f"в среднем {mean}R, 95 % ДИ {ci}, макс. просадка {dd}R\n"
            f"  оценка: {VERDICT.get(verdict, verdict)}")


def weekly_report(week_label: str, blocks: list[str]) -> str:
    body = "\n".join(blocks) if blocks else "Стратегий нет."
    return (f"Недельный отчёт forward — {week_label}\n{body}\n\n"
            f"После издержек, каждый сигнал учитывается отдельно. Ни у одной стратегии нет доказанного преимущества.\n{DISCLAIMER}")


# --- the picture's words (arven.telegram.chart) ------------------------------------------------------------------------

CHART = {
    "en": {"entry": "ENTRY", "limit": "LIMIT", "stop": "STOP", "signal": "signal", "trend line": "trend line", "entry zone": "entry zone",
           "sub": "{tf} candles to {t} UTC  ·  paper signal, not an order", "foot": "ARVEN decision support - simulated, not financial advice"},
    "ru": {"entry": "ВХОД", "limit": "ЛИМИТ", "stop": "СТОП", "signal": "сигнал", "trend line": "линия тренда", "entry zone": "зона входа",
           "sub": "свечи {tf} до {t} UTC  ·  бумажный сигнал, не ордер", "foot": "ARVEN — поддержка решений, симуляция, не финансовый совет"},
}


__all__ = ["CHART", "DISCLAIMER", "reason", "update_detail"]
