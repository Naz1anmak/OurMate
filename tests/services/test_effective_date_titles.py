from datetime import date, datetime
from zoneinfo import ZoneInfo

import src.bot.services.schedule_service as svc_mod
from src.bot.services.schedule_service import ScheduleEvent, ScheduleService

TZ = ZoneInfo("Europe/Moscow")


def _svc(events):
    svc = ScheduleService(timezone=TZ)
    svc.events = events
    return svc


def _ev(day, hh_start, hh_end):
    return ScheduleEvent(
        summary="A", location="",
        start=datetime(2026, 5, day, hh_start, 0, tzinfo=TZ),
        end=datetime(2026, 5, day, hh_end, 0, tzinfo=TZ),
        kind="Лекция",
    )


def _freeze(monkeypatch, now: datetime):
    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return now
    monkeypatch.setattr(svc_mod, "datetime", _FixedDatetime)


def test_titles_today_when_classes_ahead(monkeypatch):
    """Пары сегодня ещё впереди → сегодня / «Пары на сегодня»."""
    _freeze(monkeypatch, datetime(2026, 5, 26, 9, 0, tzinfo=TZ))
    svc = _svc([_ev(26, 10, 11)])
    eff, label, title = svc.get_effective_date_with_titles(TZ)
    assert eff == date(2026, 5, 26)
    assert label == "сегодня"
    assert title == "Пары на сегодня"


def test_titles_tomorrow_after_last_class(monkeypatch):
    """Последняя пара сегодня уже кончилась → завтра / «Пары на завтра»."""
    _freeze(monkeypatch, datetime(2026, 5, 26, 20, 0, tzinfo=TZ))
    svc = _svc([_ev(26, 10, 11)])
    eff, label, title = svc.get_effective_date_with_titles(TZ)
    assert eff == date(2026, 5, 27)
    assert label == "завтра"
    assert title == "Пары на завтра"


def test_titles_today_when_today_empty(monkeypatch):
    """Сегодня пар нет вовсе → остаёмся на сегодня (не катимся на завтра)."""
    _freeze(monkeypatch, datetime(2026, 5, 26, 20, 0, tzinfo=TZ))
    svc = _svc([_ev(27, 10, 11)])  # пары только завтра
    eff, label, title = svc.get_effective_date_with_titles(TZ)
    assert eff == date(2026, 5, 26)
    assert label == "сегодня"
    assert title == "Пары на сегодня"
