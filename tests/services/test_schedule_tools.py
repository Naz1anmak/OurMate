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
                             tool_context={"allow_refresh": False}, service=svc, refresher=None,
                             now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    assert res["empty"] is False
    assert "Предмет A" in res["formatted"]
    assert res["events"][0]["summary"] == "Предмет A"
    assert res["events"][0]["start"] == "10:00"
    assert "location" not in res["events"][0]   # место не отдаём (заочка)

@pytest.mark.asyncio
async def test_get_schedule_empty_day_shows_next():
    svc = _svc([_ev(2026, 6, 3, 10, "Предмет B")])  # пар 1 июня нет, ближайшие 3-го
    res = await get_schedule("2026-06-01", "2026-06-01",
                             tool_context={"allow_refresh": False}, service=svc, refresher=None,
                             now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    assert res["empty"] is True
    assert res["events"] == []
    assert "Предмет B" in res["formatted"]  # блок «следующие пары»

@pytest.mark.asyncio
async def test_get_schedule_empty_tomorrow_uses_word_not_number():
    # Завтра пар нет: день называем словом «завтра» без числа; ближайшие пары (не сегодня/завтра)
    # — с числом и якорем к СЕГОДНЯ, чтобы «завтра» из блока не схлопывалось с «завтра» из вопроса.
    svc = _svc([_ev(2026, 6, 1, 10, "Предмет M")])  # ближайшие — в понедельник
    res = await get_schedule("2026-05-31", "2026-05-31",
                             tool_context={"allow_refresh": False}, service=svc, refresher=None,
                             now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))  # сегодня сб, 31.05 = завтра
    assert res["empty"] is True
    assert res["events"] == []
    low = res["formatted"].lower()
    assert "завтра" in low and "31.05" not in low        # завтрашний день — словом, без числа
    assert "понедельник" in low and "01.06" in low        # ближайшие пары — с числом

@pytest.mark.asyncio
async def test_get_schedule_empty_other_day_uses_number():
    # День не сегодня/не завтра: называем «в среду (03.06)» — с числом.
    svc = _svc([_ev(2026, 6, 5, 10, "Предмет K")])
    res = await get_schedule("2026-06-03", "2026-06-03",
                             tool_context={"allow_refresh": False}, service=svc, refresher=None,
                             now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    low = res["formatted"].lower()
    assert "03.06" in low
    assert "сегодня" not in low and "завтра" not in low

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

from src.bot.services.schedule_tools import find_classes_by_subject

@pytest.mark.asyncio
async def test_find_classes_substring_case_insensitive():
    svc = _svc([_ev(2026, 6, 1, 10, "Высшая математика"),
                _ev(2026, 6, 2, 12, "Физика")])
    res = await find_classes_by_subject("матем",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    assert res["found"] is True
    assert res["events"][0]["summary"] == "Высшая математика"

@pytest.mark.asyncio
async def test_find_classes_returns_all_sorted():
    svc = _svc([_ev(2026, 6, 5, 10, "Физика"),
                _ev(2026, 6, 2, 10, "Физика")])
    res = await find_classes_by_subject("физика",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    # ближайшее первым, отдаём все занятия по предмету
    assert res["events"][0]["date"] == "2026-06-02"
    assert [e["date"] for e in res["events"]] == ["2026-06-02", "2026-06-05"]

@pytest.mark.asyncio
async def test_find_classes_surfaces_later_exam_behind_practice():
    # практика раньше, экзамен позже — экзамен не должен «прятаться» за ближайшей практикой
    practice = _ev(2026, 6, 3, 12, "Базы данных")
    exam = ScheduleEvent(summary="Базы данных", location="DL",
                         start=datetime(2026, 6, 11, 12, 0, tzinfo=TZ),
                         end=datetime(2026, 6, 11, 18, 30, tzinfo=TZ),
                         kind="Экзамен", groups=frozenset({""}))
    svc = _svc([practice, exam])
    res = await find_classes_by_subject("базы данных",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    dates = [e["date"] for e in res["events"]]
    assert "2026-06-03" in dates and "2026-06-11" in dates
    assert any(e["kind"] == "Экзамен" for e in res["events"])

@pytest.mark.asyncio
async def test_find_classes_includes_past_with_flag():
    # «был ли уже зачёт по X»: прошлое тоже ищем, помечаем past=True (баг «цифровой аналитики»).
    yesterday = ScheduleEvent(summary="Цифровая аналитика", location="DL",
                              start=datetime(2026, 5, 29, 10, 0, tzinfo=TZ),
                              end=datetime(2026, 5, 29, 13, 20, tzinfo=TZ),
                              kind="Зачет", groups=frozenset({""}))
    svc = _svc([yesterday])
    res = await find_classes_by_subject("цифровая аналитика",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))  # сегодня сб, зачёт был вчера
    assert res["found"] is True
    assert res["events"][0]["past"] is True
    assert res["events"][0]["kind"] == "Зачет"

@pytest.mark.asyncio
async def test_find_classes_token_subset_beats_morphology():
    # матчинг по токенам: «баз данных» (морфология) находит экзамен «Базы данных»,
    # хотя непрерывной подстроки «баз данных» в «базы данных» нет.
    exam = ScheduleEvent(summary="Базы данных", location="DL",
                         start=datetime(2026, 6, 11, 12, 0, tzinfo=TZ),
                         end=datetime(2026, 6, 11, 18, 30, tzinfo=TZ),
                         kind="Экзамен", groups=frozenset({""}))
    lecture = _ev(2026, 6, 1, 12, "Программирование баз данных")
    svc = _svc([exam, lecture])
    res = await find_classes_by_subject("баз данных",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    assert any(e["summary"] == "Базы данных" and e["kind"] == "Экзамен" for e in res["events"])

@pytest.mark.asyncio
async def test_find_classes_matches_declined_form():
    # юзер пишет в косвенном падеже («по цифровой аналитике»), а в расписании — именительный.
    zachet = ScheduleEvent(summary="Цифровая аналитика", location="DL",
                           start=datetime(2026, 5, 29, 10, 0, tzinfo=TZ),
                           end=datetime(2026, 5, 29, 13, 20, tzinfo=TZ),
                           kind="Зачет", groups=frozenset({""}))
    svc = _svc([zachet])
    res = await find_classes_by_subject("цифровой аналитике",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    assert res["found"] is True
    assert res["events"][0]["summary"] == "Цифровая аналитика"

@pytest.mark.asyncio
async def test_find_classes_ignores_preposition():
    # «по физике»: предлог «по» не должен требоваться к совпадению с названием.
    svc = _svc([_ev(2026, 6, 2, 10, "Физика")])
    res = await find_classes_by_subject("по физике",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    assert res["found"] is True
    assert res["events"][0]["summary"] == "Физика"

@pytest.mark.asyncio
async def test_find_classes_not_found():
    svc = _svc([_ev(2026, 6, 1, 10, "Физика")])
    res = await find_classes_by_subject("химия",
                                tool_context={"allow_refresh": False}, service=svc, refresher=None,
                                now=datetime(2026, 5, 30, 9, 0, tzinfo=TZ))
    assert res["found"] is False
    assert res["events"] == []

from src.bot.services.schedule_tools import build_schedule_registry

def test_build_registry_has_both_tools_and_gate():
    reg = build_schedule_registry(refresher=None)
    names = {s["function"]["name"] for s in reg.schemas()}
    assert names == {"get_schedule", "find_classes_by_subject"}
    assert reg.get("get_schedule").gate == "schedule_allowed"
    # схема get_schedule требует обе даты
    params = reg.get("get_schedule").schema["function"]["parameters"]
    assert set(params["required"]) == {"date_from", "date_to"}
