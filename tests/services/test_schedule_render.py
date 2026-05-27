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


def test_render_single_block_includes_kind_as_plain_line():
    """Тип занятия — строкой без буллита и без италики."""
    events = [_ev(10, 11, "Базы данных", kind="Практика")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    assert "— 10:00-11:40" in block
    assert "• <b>Базы данных</b>" in block
    assert "\nПрактика\n" in block
    assert "<i>" not in block
    assert "• Практика" not in block


def test_render_single_block_omits_kind_when_empty():
    events = [_ev(10, 11, "Программирование", kind="")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    assert "• <b>Программирование</b>" in block
    assert "<i>" not in block


def test_render_single_block_order_time_then_kind_then_summary():
    """Новый порядок: время → тип → предмет (тип перед предметом)."""
    events = [_ev(10, 11, "Базы данных", kind="Лекция")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    idx_time = block.index("— 10:00-11:40")
    idx_kind = block.index("Лекция")
    idx_summary = block.index("• <b>Базы данных</b>")
    assert idx_time < idx_kind < idx_summary
