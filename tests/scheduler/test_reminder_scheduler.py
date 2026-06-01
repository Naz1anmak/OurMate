import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from src.bot.scheduler.reminder_scheduler import classify_fire

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=TZ)


def test_future_is_scheduled():
    fut = (NOW + timedelta(hours=2)).isoformat()
    assert classify_fire(fut, NOW, misfire_hours=24) == "future"


def test_recent_past_is_late():
    past = (NOW - timedelta(hours=3)).isoformat()
    assert classify_fire(past, NOW, misfire_hours=24) == "late"


def test_old_past_is_stale():
    past = (NOW - timedelta(hours=48)).isoformat()
    assert classify_fire(past, NOW, misfire_hours=24) == "stale"
