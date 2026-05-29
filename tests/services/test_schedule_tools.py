import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from src.bot.services.schedule_tools import validate_date_range
from src.bot.services.schedule_service import ScheduleService, ScheduleEvent
from src.bot.services.schedule_tools import get_schedule

TZ = ZoneInfo("Europe/Moscow")

def _svc(events, known=frozenset({""})):
    """ScheduleService без обращения к диску (bypass __init__)."""
    s = ScheduleService.__new__(ScheduleService)
    s.timezone = TZ
    s.known_groups = known
    s.events = sorted(events, key=lambda e: e.start)
    return s

def _ev(y, m, d, h, summary, code=""):
    start = datetime(y, m, d, h, 0, tzinfo=TZ)
    end = datetime(y, m, d, h + 1, 30, tzinfo=TZ)
    return ScheduleEvent(summary=summary, location="101", start=start, end=end,
                         kind="Лекция", groups=frozenset({code}))

def test_valid_single_day():
    ok, value = validate_date_range("2026-06-01", "2026-06-01", max_days=28)
    assert ok is True
    assert value == (date(2026, 6, 1), date(2026, 6, 1))

def test_from_after_to():
    ok, value = validate_date_range("2026-06-02", "2026-06-01", max_days=28)
    assert ok is False
    assert value["error"] == "bad_range"

def test_bad_iso():
    ok, value = validate_date_range("01.06.2026", "2026-06-01", max_days=28)
    assert ok is False
    assert value["error"] == "bad_range"

def test_range_too_wide():
    ok, value = validate_date_range("2026-06-01", "2026-09-01", max_days=28)
    assert ok is False
    assert value["error"] == "bad_range"


@pytest.mark.asyncio
async def test_get_schedule_day_with_classes():
    svc = _svc([_ev(2026, 6, 1, 10, "Предмет A")])
    res = await get_schedule("2026-06-01", "2026-06-01",
                             tool_context={"allow_refresh": False}, service=svc, refresher=None)
    assert res["empty"] is False
    assert "Предмет A" in res["formatted"]
    assert res["events"][0]["summary"] == "Предмет A"
    assert res["events"][0]["start"] == "10:00"

@pytest.mark.asyncio
async def test_get_schedule_empty_day_shows_next():
    svc = _svc([_ev(2026, 6, 3, 10, "Предмет B")])  # пар 1 июня нет, ближайшие 3-го
    res = await get_schedule("2026-06-01", "2026-06-01",
                             tool_context={"allow_refresh": False}, service=svc, refresher=None)
    assert res["empty"] is True
    assert res["events"] == []
    assert "Предмет B" in res["formatted"]  # блок «следующие пары»

@pytest.mark.asyncio
async def test_get_schedule_bad_range_returns_error():
    svc = _svc([])
    res = await get_schedule("2026-06-02", "2026-06-01",
                             tool_context={"allow_refresh": False}, service=svc, refresher=None)
    assert res["error"] == "bad_range"

@pytest.mark.asyncio
async def test_get_schedule_refresh_skipped_when_not_allowed():
    calls = {"n": 0}
    class FakeRefresher:
        async def ensure_fresh(self, reason):
            calls["n"] += 1
            class R: diff_message = None
            return R()
    svc = _svc([_ev(2026, 6, 1, 10, "Предмет A")])
    await get_schedule("2026-06-01", "2026-06-01",
                       tool_context={"allow_refresh": False}, service=svc, refresher=FakeRefresher())
    assert calls["n"] == 0

@pytest.mark.asyncio
async def test_get_schedule_refresh_diff_deferred():
    class FakeRefresher:
        async def ensure_fresh(self, reason):
            class R: diff_message = "расписание изменилось"
            return R()
    svc = _svc([_ev(2026, 6, 1, 10, "Предмет A")])
    res = await get_schedule("2026-06-01", "2026-06-01",
                             tool_context={"allow_refresh": True}, service=svc, refresher=FakeRefresher())
    assert res["_deferred"] == ["расписание изменилось"]
