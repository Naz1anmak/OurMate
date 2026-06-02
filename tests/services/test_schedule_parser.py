import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.bot.services.schedule_parser import parse_lessons, normalize_kind

TZ = ZoneInfo("Europe/Moscow")
FIXTURE = json.loads((Path(__file__).parent.parent / "fixtures" / "schedule_week_sample.json").read_text())


def _flatten(payload):
    out = []
    for day in payload["days"]:
        for lesson in day["lessons"]:
            lesson = dict(lesson)
            lesson["__date"] = day["date"]
            out.append(lesson)
    return out


def test_parse_lessons_extracts_summary_time_location_kind():
    events = parse_lessons(_flatten(FIXTURE))
    assert len(events) == 2
    a, b = events
    assert a.summary == "Subject A"
    assert a.kind == "Лекция"
    assert a.location == "101, B-1"
    assert a.start == datetime(2026, 5, 26, 10, 0, tzinfo=TZ)
    assert a.end == datetime(2026, 5, 26, 11, 40, tzinfo=TZ)
    assert b.kind == "Практика"


def test_parse_lessons_extracts_groups_and_teachers():
    events = parse_lessons(_flatten(FIXTURE))
    a, b = events
    assert a.lesson_groups == frozenset({"Group A", "Group B"})
    assert a.teachers == frozenset({"Иванов И.И."})
    assert b.lesson_groups == frozenset({"Group A"})
    assert b.teachers == frozenset({"Петров П.П."})


def test_parse_lessons_extracts_webinar_url():
    events = parse_lessons(_flatten(FIXTURE))
    a, b = events
    assert a.webinar_url == "https://example.com/webinar/a"
    assert b.webinar_url == ""  # у второй пары webinar_url нет — дефолт


def test_parse_lessons_missing_groups_teachers_default_empty():
    raw = [{
        "subject": "Solo", "time_start": "14:00", "time_end": "15:40",
        "auditories": [], "typeObj": {"name": "Лекции"}, "__date": "2026-05-27",
    }]
    events = parse_lessons(raw)
    assert events[0].lesson_groups == frozenset()
    assert events[0].teachers == frozenset()
    assert events[0].webinar_url == ""


def test_normalize_kind_known_mappings():
    assert normalize_kind("Лекции") == "Лекция"
    assert normalize_kind("Практические занятия") == "Практика"
    assert normalize_kind("Лабораторные работы") == "Лаб."
    assert normalize_kind("Экзамен") == "Экзамен"
    assert normalize_kind("Зачёт") == "Зачёт"


def test_normalize_kind_unknown_passes_through():
    assert normalize_kind("Что-то новое") == "Что-то новое"


def test_normalize_kind_empty():
    assert normalize_kind("") == ""
    assert normalize_kind(None) == ""


def test_parse_lessons_skips_broken_lesson_logs_warning(caplog):
    broken = [{"subject": "Bad", "__date": "not-a-date"}]
    with caplog.at_level("WARNING"):
        events = parse_lessons(broken)
    assert events == []
    assert any("Bad" in rec.message or "lesson" in rec.message.lower() for rec in caplog.records)


def test_parse_lessons_location_without_building():
    raw = [{
        "subject": "Subject C",
        "time_start": "14:00",
        "time_end": "15:40",
        "auditories": [{"name": "303"}],
        "typeObj": {"name": "Лекции"},
        "__date": "2026-05-27",
    }]
    events = parse_lessons(raw)
    assert events[0].location == "303"


def test_parse_lessons_location_empty_when_no_auditories():
    raw = [{
        "subject": "Online",
        "time_start": "16:00",
        "time_end": "17:40",
        "auditories": [],
        "typeObj": {"name": "Лекции"},
        "__date": "2026-05-27",
    }]
    events = parse_lessons(raw)
    assert events[0].location == ""
