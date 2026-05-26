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


def test_render_single_block_includes_kind_as_italic_line():
    events = [_ev(10, 11, "Базы данных", kind="Практика")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    assert "— 10:00-11:40" in block
    assert "• <b>Базы данных</b>" in block
    assert "• <i>Практика</i>" in block


def test_render_single_block_omits_kind_when_empty():
    events = [_ev(10, 11, "Программирование", kind="")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    assert "• <b>Программирование</b>" in block
    assert "<i>" not in block


def test_render_single_block_order_time_then_summary_then_kind():
    events = [_ev(10, 11, "Базы данных", kind="Лекция")]
    block = ScheduleService._render_single_block("📌 Пары на сегодня", events)
    # Порядок строк: — время, • предмет, • тип
    idx_time = block.index("— 10:00-11:40")
    idx_summary = block.index("• <b>Базы данных</b>")
    idx_kind = block.index("• <i>Лекция</i>")
    assert idx_time < idx_summary < idx_kind
