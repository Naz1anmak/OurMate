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


def test_to_dict_from_dict_round_trip():
    ev = ScheduleEvent(
        summary="Subject A", location="101, B-1",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 11, 40, tzinfo=TZ),
        kind="Лекция",
        lesson_groups=frozenset({"Group A", "Group B"}),
        teachers=frozenset({"Иванов И.И."}),
    )
    restored = ScheduleEvent.from_dict(ev.to_dict(), group_code="40001")
    assert restored.summary == "Subject A"
    assert restored.location == "101, B-1"
    assert restored.kind == "Лекция"
    assert restored.start == ev.start
    assert restored.end == ev.end
    assert restored.lesson_groups == frozenset({"Group A", "Group B"})
    assert restored.teachers == frozenset({"Иванов И.И."})
    assert restored.groups == frozenset({"40001"})


def test_from_dict_defaults_for_legacy_json():
    legacy = {
        "summary": "X", "kind": "Лекция", "location": "101",
        "start": "2026-05-26T10:00:00+03:00", "end": "2026-05-26T11:40:00+03:00",
    }
    ev = ScheduleEvent.from_dict(legacy)
    assert ev.lesson_groups == frozenset()
    assert ev.teachers == frozenset()
    assert ev.groups == frozenset({""})


def test_to_dict_excludes_our_group_codes():
    ev = ScheduleEvent(
        summary="X", location="101",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 11, 40, tzinfo=TZ),
        groups=frozenset({"40001"}),
    )
    assert "groups" not in ev.to_dict()
