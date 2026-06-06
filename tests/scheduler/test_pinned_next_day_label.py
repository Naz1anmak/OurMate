"""Регресс закрепа: «Пар завтра нет» не должно соседствовать с блоком «Пары завтра».

Инцидент 06.06: вечером, после того как сегодняшний экзамен кончился, effective_date
укатился на 07.06 (завтра). Завтра пар нет, ближайший экзамен — 08.06 (послезавтра).
Закреп выводил «Пар завтра нет» и тут же «Пары завтра …» с тем самым экзаменом —
самопротиворечие: «пар нет, но они есть».
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import src.bot.services.schedule_service as svc_mod
from src.bot.services.schedule_service import ScheduleEvent
from src.bot.scheduler import pinned_schedule_scheduler as pin_mod

TZ = ZoneInfo("Europe/Moscow")


def _ev(day, hh_start, hh_end):
    return ScheduleEvent(
        summary="Экзамен", location="",
        start=datetime(2026, 6, day, hh_start, 0, tzinfo=TZ),
        end=datetime(2026, 6, day, hh_end, 0, tzinfo=TZ),
        kind="Экзамен",
    )


def _freeze(monkeypatch, now: datetime):
    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return now
    monkeypatch.setattr(svc_mod, "datetime", _FixedDatetime)


def test_pinned_no_tomorrow_label_when_effective_rolled_forward(monkeypatch):
    _freeze(monkeypatch, datetime(2026, 6, 6, 20, 0, tzinfo=TZ))
    svc = svc_mod.schedule_service
    monkeypatch.setattr(svc, "events", [_ev(6, 10, 15), _ev(8, 10, 15)])
    monkeypatch.setattr(svc, "known_groups", frozenset({""}))

    text = pin_mod._build_pinned_text()

    assert text is not None
    # «Пар завтра нет» (про 07.06) — корректно, его оставляем.
    assert "завтра нет" in text
    # …но блок ближайших пар про 08.06 НЕ должен называться «Пары завтра».
    assert "Пары завтра" not in text
    assert "08.06" in text
