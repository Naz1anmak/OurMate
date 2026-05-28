from datetime import datetime
from zoneinfo import ZoneInfo

from src.bot.services.schedule_service import ScheduleEvent, ScheduleService

TZ = ZoneInfo("Europe/Moscow")


def _ev(hh_start, hh_end, summary, kind=""):
    return ScheduleEvent(
        summary=summary,
        location="",
        start=datetime(2026, 5, 26, hh_start, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, hh_end, 40, tzinfo=TZ),
        kind=kind,
    )


def test_render_single_block_time_kind_inline_subject_below():
    """Время и тип на одной строке через ' · ', предмет жирным на следующей."""
    events = [_ev(10, 11, "Вычислительная математика", kind="Лекция")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    assert "10:00–11:40 · Лекция\n<b>Вычислительная математика</b>" in block
    assert "— " not in block
    assert "• " not in block
    assert "<i>" not in block


def test_render_single_block_omits_kind_when_empty():
    """Без типа — только время на первой строке."""
    events = [_ev(10, 11, "Программирование", kind="")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    assert "10:00–11:40\n<b>Программирование</b>" in block
    assert " · " not in block


def test_render_single_block_blank_line_between_pairs():
    """Между парами — пустая строка."""
    events = [
        _ev(10, 11, "Базы данных", kind="Лекция"),
        _ev(12, 13, "Сети", kind="Практика"),
    ]
    block = ScheduleService._render_single_block("📌 Пары", events)
    assert (
        "10:00–11:40 · Лекция\n<b>Базы данных</b>\n\n12:00–13:40 · Практика\n<b>Сети</b>"
        in block
    )


def test_render_single_block_escapes_html_in_summary():
    """Спецсимволы в summary эскейпятся (Telegram parse_mode=HTML)."""
    events = [_ev(10, 11, "A & B <C>", kind="Лекция")]
    block = ScheduleService._render_single_block("📌 Пары", events)
    assert "<b>A &amp; B &lt;C&gt;</b>" in block
    assert "<b>A & B <C></b>" not in block
