from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.bot.services.ruz_parser import save_schedule, load_schedule
from src.bot.services.schedule_service import ScheduleEvent

TZ = ZoneInfo("Europe/Moscow")


@pytest.fixture
def tmp_groups_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.bot.services.ruz_parser.SCHEDULE_GROUPS_DIR", tmp_path)
    return tmp_path


def _ev(hh, summary="X", kind="Лекция"):
    return ScheduleEvent(
        summary=summary, location="101, B-1",
        start=datetime(2026, 5, 26, hh, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, hh, 40, tzinfo=TZ),
        kind=kind,
    )


def test_save_load_round_trip(tmp_groups_dir):
    events = [_ev(10), _ev(12, summary="Y", kind="Практика")]
    fetched = datetime(2026, 5, 26, 9, 0, tzinfo=TZ)
    save_schedule("40001", events, fetched_at=fetched)

    loaded_fetched, loaded_events = load_schedule("40001")
    assert loaded_fetched == fetched
    assert len(loaded_events) == 2
    assert loaded_events[0].summary == "X"
    assert loaded_events[0].kind == "Лекция"
    assert loaded_events[1].kind == "Практика"


def test_load_returns_none_and_empty_when_no_file(tmp_groups_dir):
    fetched, events = load_schedule("40001")
    assert fetched is None
    assert events == []


def test_load_handles_corrupted_json(tmp_groups_dir, caplog):
    group_dir = tmp_groups_dir / "40001"
    group_dir.mkdir()
    (group_dir / "schedule.json").write_text("{not json")
    with caplog.at_level("WARNING"):
        fetched, events = load_schedule("40001")
    assert fetched is None
    assert events == []


def test_save_atomic_uses_tmp_then_rename(tmp_groups_dir):
    save_schedule("40001", [_ev(10)], fetched_at=datetime(2026, 5, 26, 9, 0, tzinfo=TZ))
    assert (tmp_groups_dir / "40001" / "schedule.json").exists()
    assert not (tmp_groups_dir / "40001" / "schedule.json.tmp").exists()


def test_save_with_empty_events_writes_empty_list(tmp_groups_dir):
    save_schedule("40001", [], fetched_at=datetime(2026, 5, 26, 9, 0, tzinfo=TZ))
    fetched, events = load_schedule("40001")
    assert events == []
    assert fetched is not None
