"""Russian wording (config/live.yaml telegram.language: ru): every reason template the strategies write and every update
kind is translated, numbers are the same as in the English text, the English wording is unchanged, and the picture
falls back to English words when no Cyrillic font is installed."""

from __future__ import annotations

import pytest

from arven.core.live_config import LiveTelegramConfig, load_live_config
from arven.engine.signal_events import SignalUpdate, SignalUpdateKind
from arven.telegram import chart as chart_mod
from arven.telegram import ru
from arven.telegram.client import CAPTION_LIMIT
from arven.telegram.commands import HELP_TEXT, RU, CommandContext, handle_command
from arven.telegram.messages import (
    DISCLAIMER,
    DailySummarySection,
    TrackRecord,
    WeeklyReportRow,
    chart_title,
    format_daily_summary,
    format_new_signal,
    format_signal_update,
    format_system_alert,
    format_weekly_report,
    update_label,
)

from test_messages import make_signal

# one real example of every reason template in the signal stores (S4, S5, S6, S7, Crowded Shorts)
REASONS = {
    "impulse bearish size=2.31": "импульс вниз, размер 2.31",
    "zone=[4120.5,4131.2] overlap=64%": "зона [4120.5; 4131.2], перекрытие 64%",
    "4h ema_slope_50 agrees with impulse direction": "наклон EMA50 на 4h совпадает с направлением импульса",
    "4h ema_slope_50 agrees with breakout direction": "наклон EMA50 на 4h совпадает с направлением пробоя",
    "4h ema_slope_50 agrees with the trade direction": "наклон EMA50 на 4h совпадает с направлением сделки",
    "squeeze range [4100.0,4120.0] width=1.8 ATR": "сжатие в диапазоне [4100.0; 4120.0], ширина 1.8 ATR",
    "pullback to 1h EMA50 (4111.2) held, bounce on 15m": "откат к EMA50 на 1h (4111.2) удержался, отскок на 15m",
    "15m trend line broken, fib retest setup armed (level 0 4182.63, level 1 4167.50)":
        "15m: линия тренда пробита, ждём отката по Фибоначчи (уровень 0 4182.63, уровень 1 4167.50)",
    "entry: limit 4175.07 (fib 0.5); cancelled if a 15m bar closes beyond level 0 or above level 1, expires if unfilled":
        "вход: лимит 4175.07 (fib 0.5); отмена, если свеча 15m закроется за уровнем 0 или выше уровня 1; ордер истекает, если не исполнится",
    "confluence zones: fvg, ifvg, level, order_block": "зоны совпадения: FVG, iFVG, уровень, ордер-блок",
    "funding z-score -1.83 <= -1.5 and open-interest z-score 1.22 >= 1 (crowded shorts)":
        "z-оценка фандинга -1.83 ≤ -1.5, z-оценка открытого интереса 1.22 ≥ 1 (перегруженные шорты)",
    "market buy now; stop 3% below the fill; no take-profit": "покупка по рынку сейчас; стоп на 3% ниже входа; без тейк-профита",
    "exit 24 h after the last qualifying signal (a repeat signal extends the hold)":
        "выход через 24 ч после последнего подходящего сигнала (повторный сигнал продлевает удержание)",
}


@pytest.mark.parametrize("en,expected", list(REASONS.items()))
def test_every_reason_template_is_translated(en, expected):
    assert ru.reason(en) == expected


def test_an_unknown_reason_is_shown_unchanged():
    assert ru.reason("something new 1.5") == "something new 1.5"


UPDATES = [
    (SignalUpdateKind.TP_HIT, "level=TP1;fraction=0.50000000;price=4135.12345678", "TP1: закрыто 50 % позиции по 4135.12"),
    (SignalUpdateKind.CLOSED, "reason=STOP;fraction=1.00000000", "Позиция закрыта по стопу: закрыто 100 % позиции"),
    (SignalUpdateKind.CLOSED, "reason=TIME_STOP;fraction=1.00000000;price=4100.5", "Позиция закрыта по времени по 4100.50: закрыто 100 % позиции"),
    (SignalUpdateKind.CLOSED, "reason=STOP_TRAIL;fraction=0.5;leg=2", "Позиция закрыта по подтянутому стопу: закрыто 50 % позиции (часть 2)"),
    (SignalUpdateKind.FILLED, "price=4175.07000000;weight=1", "Вход исполнен по 4175.07"),
    (SignalUpdateKind.FILLED, "price=4175.07000000;weight=0.5;leg=1", "Вход исполнен по 4175.07, доля 0.5 (часть 1)"),
    (SignalUpdateKind.STOP_MOVED, "new_stop=4170.00000000", "Новый стоп: 4170.00"),
    (SignalUpdateKind.CANCELLED, "reason=level1_moved", "Причина: уровень 1 сдвинулся (сетап перестроен)"),
    (SignalUpdateKind.CANCELLED, "reason=zone_broken_by_impulse", "Причина: зону входа пробил импульс"),
    (SignalUpdateKind.CANCELLED, "reason=expired", "Причина: лимитный ордер не исполнился за отведённое время"),
]


@pytest.mark.parametrize("kind,detail,expected", UPDATES)
def test_every_update_kind_reads_as_words(kind, detail, expected):
    s = make_signal()
    u = SignalUpdate(s.signal_id, 1000, kind, detail)
    assert ru.update_detail(u) == expected
    text = format_signal_update(s, u, "ru")
    assert expected in text and ru.DISCLAIMER in text and "100.00" in text and "98.00" in text


def test_new_signal_in_russian_has_the_same_numbers_as_in_english():
    s = make_signal(reasons=tuple(list(REASONS)[:3]))
    rec = TrackRecord(27, 11, -11.51, 1_782_864_000_000)
    en, text = format_new_signal(s, rec), format_new_signal(s, rec, "ru")
    assert text.startswith("НОВЫЙ СИГНАЛ [ЭКСПЕРИМЕНТ]") and "ПОКУПКА (LONG)" in text
    for number in ("100.00", "98.00", "102.00", "104.00", "-11.51"):
        assert number in en and number in text
    assert "Риск: 1.00 % депозита" in text and "закрыть 50 %" in text
    assert "Результаты стратегии (на бумаге с 01.07.2026): закрыто 27, в плюсе 41 %, итог -11.51 R" in text
    assert "  • импульс вниз, размер 2.31" in text and DISCLAIMER not in text and ru.DISCLAIMER in text
    assert "Результаты стратегии: нет данных" in format_new_signal(s, None, "ru")
    assert "закрытых сигналов пока нет" in format_new_signal(s, TrackRecord(0, 0, 0.0, 1_782_864_000_000), "ru")
    assert len(format_new_signal(make_signal(reasons=tuple(list(REASONS)[7:10])), rec, "ru")) <= CAPTION_LIMIT


def test_english_is_still_the_default_and_unchanged():
    s = make_signal()
    assert format_new_signal(s) == format_new_signal(s, None, "en") and format_new_signal(s).startswith("NEW SIGNAL")
    assert LiveTelegramConfig().language == "en"


def test_the_repo_config_sends_russian():
    assert load_live_config().telegram.language == "ru"


def test_titles_labels_summaries_alerts_in_russian():
    s = make_signal()
    u = SignalUpdate(s.signal_id, 1000, SignalUpdateKind.CLOSED, "reason=STOP;fraction=1")
    assert update_label(u, "ru") == "Закрыто по стопу" and chart_title(s, u, "ru").startswith("Закрыто по стопу: BTCUSDT · LONG")
    assert update_label(SignalUpdate(s.signal_id, 1000, SignalUpdateKind.TP_HIT, "level=TP2;fraction=0.3;price=1"), "ru") == "TP2 достигнута"
    daily = format_daily_summary("2026-10-21", (DailySummarySection("s7", "EXPERIMENTAL", 3, 2, -1.25),), "ru")
    assert "Итоги дня — 2026-10-21" in daily and "s7 [ЭКСПЕРИМЕНТ]: сигналов 3, закрыто 2, итог -1.25R" in daily
    assert "Сигналов за день не было." in format_daily_summary("2026-10-21", (), "ru")
    row = WeeklyReportRow("s7", "EXPERIMENTAL", 27, 0, -11.51, 0.41, -0.43, -0.9, 0.04, 14.2, "inconclusive", 3, -1.0)
    weekly = format_weekly_report("2026-10-12 - 2026-10-18", "2026-07-01", (row,), "ru")
    assert "Недельный отчёт forward" in weekly and "с 2026-07-01: закрыто 27 (открыто 0), -11.51R, в плюсе 41 %" in weekly
    assert "оценка: неясно: 95 % интервал содержит 0" in weekly
    assert format_system_alert("Gold: market data stale", "detail", "ru") == "СИСТЕМНОЕ ПРЕДУПРЕЖДЕНИЕ: Gold: данные рынка устарели\ndetail"
    assert format_system_alert("live loop started", "d", "ru").startswith("СИСТЕМНОЕ ПРЕДУПРЕЖДЕНИЕ: live-цикл запущен")


def test_bot_replies_in_russian(tmp_path):
    from arven.data.storage.db import connect

    ctx = CommandContext(connect(":memory:"), tmp_path / "signals", tmp_path / "hb.json", 0, lang="ru")
    assert handle_command("/help", "1", ctx) == RU["help"] != HELP_TEXT
    assert handle_command("/signals", "1", ctx) == "Сигналов пока нет."
    assert handle_command("/status", "1", ctx).startswith("Данных о работе процесса ещё нет")
    assert handle_command("/pause", "1", ctx).startswith("Пауза")


def test_the_picture_falls_back_to_english_words_without_a_cyrillic_font(monkeypatch):
    from test_chart import _candles, _signal_at

    s = _signal_at(120)
    if chart_mod.cyrillic_font() is not None:
        assert chart_mod.chart_language("ru") == "ru"
        assert [lbl for lbl, _, _ in chart_mod.level_labels(s, "ru")][:2] == ["ВХОД 100.00", "СТОП 98.00"]
        ru_png = chart_mod.render_signal_chart(s, _candles(s.event_time_ms), chart_title(s, None, "ru"), lang="ru")
        assert ru_png.startswith(b"\x89PNG")
    monkeypatch.setattr(chart_mod, "cyrillic_font", lambda: None)
    assert chart_mod.chart_language("ru") == "en"
    en_png = chart_mod.render_signal_chart(s, _candles(s.event_time_ms), chart_title(s), lang="en")
    assert chart_mod.render_signal_chart(s, _candles(s.event_time_ms), chart_title(s), lang="ru") == en_png


def test_event_reminder_text_in_both_languages():
    from datetime import UTC, datetime

    from arven.core.time import to_ms
    from arven.telegram.messages import EventReminderRow, format_event_reminder

    t = to_ms(datetime(2026, 10, 28, 18, 0, tzinfo=UTC))
    rows = (EventReminderRow("BTC", 55, 2.0484, 14.8931, 0.7685), EventReminderRow("Gold", 0, None, None, None))
    ru_text = format_event_reminder("FOMC", t, 60, rows, "ru")
    assert ru_text.startswith("Через 60 мин: решение ФРС по ставке (FOMC), 28.10.2026 18:00 UTC")
    assert "BTC: медиана 2.05 %, максимум 14.89 %, в обычный день в этот час 0.77 % (55 публикаций)" in ru_text
    assert "Золото: истории пока нет" in ru_text and "не прогноз" in ru_text
    en = format_event_reminder("CPI", t, 60, rows, "en")
    assert en.startswith("In 60 min: US inflation, CPI, 2026-10-28 18:00 UTC") and "not a forecast" in en


def test_mistakes_summary_in_both_languages():
    from arven.telegram.messages import format_mistakes_summary

    p = {"strategy": "s4_impulse_retest", "part": "history", "feature": "weekday", "value": "Thu", "flag": "better", "trades": 37,
         "mean_r": 1.66, "rest_mean_r": 0.05}
    blocks = (("BTC", "2026-10-24T01:00:00+00:00", (p,)), ("Gold", None, ()))
    ru_text = format_mistakes_summary(blocks, "ru")
    assert ru_text.startswith("Работа над ошибками") and "BTC (посчитано 2026-10-24):" in ru_text
    assert "s4_impulse_retest (история): день недели = Thu - лучше обычного, 37 сделок, +1.66R против +0.05R" in ru_text
    assert "Золото (ещё не посчитано): явно плохих или хороших обстановок пока нет" in ru_text and "а не изменения" in ru_text
    en = format_mistakes_summary(blocks, "en")
    assert "Gold (not built yet): no circumstance is clearly worse or better yet" in en and "not changes" in en


def test_conflict_note_in_russian():
    from arven.live.conflicts import ActiveSignal, priority
    from arven.telegram.messages import format_conflict_note

    t = 1_792_000_800_000
    o = ActiveSignal("x", "s7_4h", "S7 4h", "4h", 1, t, None, priority("4h", 0))
    note = format_conflict_note([o], [], "block", "ru")
    assert note.startswith("НЕ ВХОДИТЬ: противоречит активному сигналу: S7 4h (4h, ЛОНГ с ") and "только для статистики" in note
    assert format_conflict_note([o], [], "note", "ru").startswith("Противоречит активному сигналу")
    assert format_conflict_note([], [o], "block", "ru").startswith("Подтверждает: S7 4h (4h, ЛОНГ")
    assert format_conflict_note([o], [], "off", "ru") is None and format_conflict_note([], [], "block", "ru") is None
