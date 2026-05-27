import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from src.bot.services.ruz_parser import save_schedule
from src.bot.services.ruz_client import RuzError
from src.bot.services.schedule_refresher import ScheduleRefresher
from src.bot.services.schedule_service import ScheduleEvent
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Moscow")
FIXTURE_RAW = [
    {
        "subject": "Subject A", "time_start": "10:00", "time_end": "11:40",
        "auditories": [{"name": "101", "building": {"name": "B-1"}}],
        "typeObj": {"name": "Лекции"}, "__date": "2026-05-26",
    }
]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr("src.bot.services.ruz_parser.SCHEDULE_GROUPS_DIR", tmp_path)
    monkeypatch.setattr("src.bot.services.schedule_service.SCHEDULE_GROUPS_DIR", tmp_path)
    monkeypatch.setattr("src.bot.services.schedule_refresher.SCHEDULE_GROUPS_DIR", tmp_path)
    return tmp_path


def _stub_service():
    svc = MagicMock()
    svc.reload = MagicMock(return_value=None)
    return svc


@pytest.mark.asyncio
@freeze_time("2026-05-26 09:00:00", tz_offset=3)
async def test_force_refresh_calls_client_and_saves(isolated_data):
    (isolated_data / "40001").mkdir()
    client = AsyncMock()
    client.fetch_week = AsyncMock(return_value=FIXTURE_RAW)

    schedule_service = _stub_service()
    refresher = ScheduleRefresher(
        client=client,
        schedule_service=schedule_service,
        group_ids={"40001": 99000},
        weeks_ahead=3,
        lazy_ttl_min=60,
    )
    result = await refresher.force_refresh("test")
    assert "40001" in result.updated_groups
    schedule_service.reload.assert_called_once()
    assert (isolated_data / "40001" / "schedule.json").exists()


@pytest.mark.asyncio
@freeze_time("2026-05-26 09:00:00", tz_offset=3)
async def test_ensure_fresh_skips_when_within_ttl(isolated_data):
    (isolated_data / "40001").mkdir()
    # Свежий snapshot: freeze_time(tz_offset=3) даёт datetime.now(TZ)=15:00 MSK;
    # сохраняем 14:50 MSK — разница 10 мин < TTL 60 мин → должны пропустить.
    save_schedule("40001", [], fetched_at=datetime(2026, 5, 26, 14, 50, tzinfo=TZ))

    client = AsyncMock()
    schedule_service = _stub_service()
    refresher = ScheduleRefresher(
        client=client, schedule_service=schedule_service,
        group_ids={"40001": 99000}, weeks_ahead=3, lazy_ttl_min=60,
    )
    result = await refresher.ensure_fresh("test")
    assert result.skipped_groups == ["40001"]
    client.fetch_week.assert_not_called()


@pytest.mark.asyncio
@freeze_time("2026-05-26 09:00:00", tz_offset=3)
async def test_ensure_fresh_refreshes_when_ttl_expired(isolated_data):
    (isolated_data / "40001").mkdir()
    save_schedule("40001", [], fetched_at=datetime(2026, 5, 26, 7, 0, tzinfo=TZ))

    client = AsyncMock()
    client.fetch_week = AsyncMock(return_value=FIXTURE_RAW)
    schedule_service = _stub_service()
    refresher = ScheduleRefresher(
        client=client, schedule_service=schedule_service,
        group_ids={"40001": 99000}, weeks_ahead=3, lazy_ttl_min=60,
    )
    result = await refresher.ensure_fresh("test")
    assert "40001" in result.updated_groups
    client.fetch_week.assert_called()


@pytest.mark.asyncio
@freeze_time("2026-05-26 09:00:00", tz_offset=3)
async def test_all_weeks_fail_does_not_overwrite_old_snapshot(isolated_data):
    (isolated_data / "40001").mkdir()
    save_schedule("40001", [], fetched_at=datetime(2026, 5, 25, 9, 0, tzinfo=TZ))

    client = AsyncMock()
    client.fetch_week = AsyncMock(side_effect=RuzError("сеть"))
    schedule_service = _stub_service()
    refresher = ScheduleRefresher(
        client=client, schedule_service=schedule_service,
        group_ids={"40001": 99000}, weeks_ahead=3, lazy_ttl_min=60,
    )
    result = await refresher.force_refresh("test")
    assert "40001" in result.failed_groups
    # fetched_at не двинулся
    raw = json.loads((isolated_data / "40001" / "schedule.json").read_text())
    assert raw["fetched_at"].startswith("2026-05-25")


@pytest.mark.asyncio
@freeze_time("2026-05-26 09:00:00", tz_offset=3)
async def test_partial_failure_still_writes_what_we_have(isolated_data):
    (isolated_data / "40001").mkdir()
    client = AsyncMock()
    # 1-я неделя ок, остальные падают
    client.fetch_week = AsyncMock(side_effect=[FIXTURE_RAW, RuzError("сеть"), RuzError("сеть"), RuzError("сеть")])
    schedule_service = _stub_service()
    refresher = ScheduleRefresher(
        client=client, schedule_service=schedule_service,
        group_ids={"40001": 99000}, weeks_ahead=3, lazy_ttl_min=60,
    )
    result = await refresher.force_refresh("test")
    assert "40001" in result.updated_groups
    raw = json.loads((isolated_data / "40001" / "schedule.json").read_text())
    assert len(raw["events"]) >= 1


@pytest.mark.asyncio
@freeze_time("2026-05-26 09:00:00", tz_offset=3)
async def test_skip_group_without_group_id(isolated_data):
    (isolated_data / "40001").mkdir()
    (isolated_data / "40002").mkdir()
    client = AsyncMock()
    client.fetch_week = AsyncMock(return_value=FIXTURE_RAW)
    schedule_service = _stub_service()
    refresher = ScheduleRefresher(
        client=client, schedule_service=schedule_service,
        group_ids={"40001": 99000},  # 40002 без id
        weeks_ahead=3, lazy_ttl_min=60,
    )
    result = await refresher.force_refresh("test")
    assert "40001" in result.updated_groups
    assert "40002" in result.skipped_groups
