"""Заголовок блока «следующие пары» должен якорить релятивное «завтра» к РЕАЛЬНОМУ
сегодня, а не к дате, от которой искали ближайшие пары.

Регресс: вечером дня с парами effective_date укатывается на завтра. Если завтра пар
нет, а ближайшие — послезавтра, блок ошибочно подписывался «Пары завтра», прямо
противореча строке «Пар завтра нет» над ним.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import src.bot.services.schedule_service as svc_mod
from src.bot.services.schedule_service import ScheduleEvent, ScheduleService

TZ = ZoneInfo("Europe/Moscow")


def _svc(events):
    svc = ScheduleService(timezone=TZ)
    svc.events = events
    svc.known_groups = frozenset({""})
    return svc


def _ev(day, hh_start, hh_end, summary="Экзамен СиА", kind="Экзамен"):
    return ScheduleEvent(
        summary=summary, location="",
        start=datetime(2026, 6, day, hh_start, 0, tzinfo=TZ),
        end=datetime(2026, 6, day, hh_end, 0, tzinfo=TZ),
        kind=kind,
    )


def _freeze(monkeypatch, now: datetime):
    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return now
    monkeypatch.setattr(svc_mod, "datetime", _FixedDatetime)


def test_next_block_after_today_over_is_not_labeled_tomorrow(monkeypatch):
    """Вечер 06.06 (пары кончились), завтра 07.06 пусто, ближайшие — 08.06.
    Блок про 08.06 НЕ должен называться «Пары завтра» (это послезавтра)."""
    _freeze(monkeypatch, datetime(2026, 6, 6, 20, 0, tzinfo=TZ))
    svc = _svc([_ev(8, 10, 15)])
    block = svc.format_next_classes_block(svc.events[0].start.date())
    assert "Пары завтра" not in block
    assert "08.06" in block


def test_next_block_real_tomorrow_is_labeled_tomorrow(monkeypatch):
    """Если ближайший день действительно завтра — подпись «Пары завтра» сохраняется."""
    _freeze(monkeypatch, datetime(2026, 6, 6, 20, 0, tzinfo=TZ))
    svc = _svc([_ev(7, 10, 15)])
    block = svc.format_next_classes_block(svc.events[0].start.date())
    assert "Пары завтра" in block
