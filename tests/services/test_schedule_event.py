from datetime import datetime
from zoneinfo import ZoneInfo

from src.bot.services.schedule_service import ScheduleEvent

TZ = ZoneInfo("Europe/Moscow")


def test_schedule_event_has_kind_default_empty():
    ev = ScheduleEvent(
        summary="Базы данных",
        location="Ауд. 101",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 11, 40, tzinfo=TZ),
    )
    assert ev.kind == ""


def test_schedule_event_kind_explicit():
    ev = ScheduleEvent(
        summary="Базы данных",
        location="Ауд. 101",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 11, 40, tzinfo=TZ),
        kind="Практика",
    )
    assert ev.kind == "Практика"


def test_schedule_event_key_does_not_include_kind():
    """Дубликаты с разным kind должны считаться одним событием для merge."""
    base = dict(
        summary="Базы данных",
        location="Ауд. 101",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 11, 40, tzinfo=TZ),
    )
    a = ScheduleEvent(**base, kind="Лекция")
    b = ScheduleEvent(**base, kind="Практика")
    assert a.key() == b.key()
