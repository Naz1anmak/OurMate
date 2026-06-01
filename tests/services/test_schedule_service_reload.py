from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.bot.services.ruz_parser import save_schedule
from src.bot.services.schedule_service import ScheduleEvent, ScheduleService

TZ = ZoneInfo("Europe/Moscow")


@pytest.fixture
def tmp_groups_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.bot.services.ruz_parser.SCHEDULE_GROUPS_DIR", tmp_path)
    monkeypatch.setattr("src.bot.services.schedule_service.SCHEDULE_GROUPS_DIR", tmp_path)
    return tmp_path


def _ev(code, hh):
    return ScheduleEvent(
        summary="X", location="",
        start=datetime(2026, 5, 26, hh, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, hh, 40, tzinfo=TZ),
        groups=frozenset({code}),
        kind="Лекция",
    )


def test_read_schedule_json_stamps_group_code_and_reads_lesson_groups(tmp_groups_dir):
    ev = ScheduleEvent(
        summary="X", location="101",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 11, 40, tzinfo=TZ),
        kind="Лекция", lesson_groups=frozenset({"Group A"}),
    )
    save_schedule("40001", [ev], fetched_at=datetime(2026, 5, 26, 9, 0, tzinfo=TZ))
    loaded = ScheduleService._read_schedule_json(tmp_groups_dir / "40001" / "schedule.json", "40001")
    assert loaded[0].groups == frozenset({"40001"})
    assert loaded[0].lesson_groups == frozenset({"Group A"})


def test_load_events_from_schedule_json_per_group(tmp_groups_dir):
    save_schedule("40001", [_ev("40001", 10)], fetched_at=datetime(2026, 5, 26, 9, 0, tzinfo=TZ))
    save_schedule("40002", [_ev("40002", 12)], fetched_at=datetime(2026, 5, 26, 9, 0, tzinfo=TZ))
    svc = ScheduleService()
    assert len(svc.events) == 2
    assert svc.known_groups == frozenset({"40001", "40002"})


def test_reload_picks_up_new_data(tmp_groups_dir):
    save_schedule("40001", [], fetched_at=datetime(2026, 5, 26, 9, 0, tzinfo=TZ))
    svc = ScheduleService()
    assert svc.events == []

    save_schedule("40001", [_ev("40001", 10)], fetched_at=datetime(2026, 5, 26, 10, 0, tzinfo=TZ))
    svc.reload()
    assert len(svc.events) == 1


def test_load_skips_groups_without_schedule_json(tmp_groups_dir):
    (tmp_groups_dir / "40001").mkdir()  # подпапка есть, но schedule.json нет
    svc = ScheduleService()
    assert svc.events == []
    assert svc.known_groups == frozenset({"40001"})
