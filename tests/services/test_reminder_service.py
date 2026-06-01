import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from src.bot.services import reminder_service as rs

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)  # понедельник


def _rem(**kw):
    base = {"id": 1, "text": "созвон", "fire_at": "2026-06-01T19:00:00+03:00",
            "scope": "chat", "chat_id": -100, "author_id": 42, "status": "pending"}
    base.update(kw)
    return base


def test_humanize_today_tomorrow_and_dated():
    assert rs.humanize_dt(datetime(2026, 6, 1, 19, 0, tzinfo=TZ), NOW) == "сегодня, 19:00"
    assert rs.humanize_dt(datetime(2026, 6, 2, 10, 0, tzinfo=TZ), NOW) == "завтра, 10:00"
    # остальные дни — с числом
    assert rs.humanize_dt(datetime(2026, 6, 5, 15, 0, tzinfo=TZ), NOW) == "пт, 5 июн, 15:00"


def test_render_list_compact():
    items = [_rem(id=1, text="Созвон", fire_at="2026-06-01T19:00:00+03:00"),
             _rem(id=2, text="Сдать лабу", fire_at="2026-06-02T10:00:00+03:00")]
    out = rs.render_list(items, header="Напоминания беседы", now=NOW)
    assert "Напоминания беседы (2)" in out
    assert "1. Созвон — сегодня, 19:00" in out
    assert "2. Сдать лабу — завтра, 10:00" in out


def test_render_list_empty():
    out = rs.render_list([], header="Твои напоминания", now=NOW)
    assert "Пока напоминаний нет" in out


def test_can_modify():
    rem = _rem(author_id=42)
    assert rs.can_modify(rem, user_id=42, is_owner=False) is True
    assert rs.can_modify(rem, user_id=7, is_owner=True) is True
    assert rs.can_modify(rem, user_id=7, is_owner=False) is False


def test_render_ping_uses_tg_user_links():
    rem = _rem(text="Созвон")
    subs = [{"user_id": 7, "first_name": "Аня", "username": "anya"},
            {"user_id": 8, "first_name": None, "username": None}]
    chunks = rs.render_ping(rem, subs)
    assert len(chunks) == 1
    text = chunks[0]
    assert 'tg://user?id=7' in text and 'tg://user?id=8' in text
    assert "Аня" in text and "Созвон" in text


def test_render_ping_splits_over_50():
    rem = _rem()
    subs = [{"user_id": i, "first_name": f"U{i}", "username": None} for i in range(120)]
    chunks = rs.render_ping(rem, subs)
    assert len(chunks) == 3  # 50 + 50 + 20


def test_render_created_has_no_question():
    rem = _rem(text="Почистить зубы", fire_at="2026-06-01T15:23:00+03:00")
    out = rs.render_created(rem, NOW)
    assert "Почистить зубы" in out
    assert "▎ сегодня, 15:23" in out
    assert "Создаём?" not in out          # подтверждённое состояние — без вопроса


def test_render_confirm_pm_uses_bar_marker():
    rem = _rem(text="Созвон", fire_at="2026-06-01T19:00:00+03:00")
    out = rs.render_confirm_pm(rem, NOW)
    assert "▎ сегодня, 19:00" in out       # время помечено ▎, без эмодзи-календаря
    assert "🗓" not in out


def test_make_diff():
    old = _rem(text="Созвон", fire_at="2026-06-01T18:00:00+03:00")
    diff = rs.make_diff(old, new_text=None, new_fire_at="2026-06-01T19:00:00+03:00", now=NOW)
    assert "18:00" in diff and "19:00" in diff
