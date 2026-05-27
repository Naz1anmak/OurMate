from datetime import datetime, date
from zoneinfo import ZoneInfo

from src.bot.services.schedule_diff import DayDiff, DiffSummary, render
from src.bot.services.schedule_service import ScheduleEvent

TZ = ZoneInfo("Europe/Moscow")


def _ev(hh, summary="A", kind="Лекция"):
    return ScheduleEvent(
        summary=summary, location="",
        start=datetime(2026, 5, 26, hh, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, hh, 40, tzinfo=TZ),
        kind=kind,
    )


def test_render_empty_summary_returns_none():
    assert render(DiffSummary()) is None


def test_render_appearance_short_header_only():
    text = render(DiffSummary(is_appearance=True))
    assert text == "🗓️ Появилось расписание!"


def test_render_diff_has_emoji_plus_for_added():
    day = DayDiff(date=date(2026, 5, 26), group_code="40001", added=[_ev(12, "Базы данных", "Практика")])
    text = render(DiffSummary(days=[day]))
    assert "🗓️ Расписание обновилось" in text
    assert "➕" in text
    assert "Базы данных" in text
    assert "Практика" in text
    assert "26.05" in text


def test_render_diff_has_emoji_minus_for_removed():
    day = DayDiff(date=date(2026, 5, 26), group_code="40001", removed=[_ev(14, "Программирование", "Лекция")])
    text = render(DiffSummary(days=[day]))
    assert "➖" in text
    assert "Программирование" in text


def test_render_diff_has_pencil_for_changed():
    before = _ev(10, "Админ ИС", "Лекция")
    after = _ev(12, "Админ ИС", "Лекция")
    day = DayDiff(date=date(2026, 5, 26), group_code="40001", changed=[(before, after)])
    text = render(DiffSummary(days=[day]))
    assert "✏️" in text
    assert "10:00-10:40 → 12:00-12:40" in text


def test_render_per_group_label_only_when_groups_differ():
    day_a = DayDiff(date=date(2026, 5, 26), group_code="40001", added=[_ev(10)])
    day_b = DayDiff(date=date(2026, 5, 26), group_code="40002", added=[_ev(12)])
    text = render(DiffSummary(days=[day_a, day_b]))
    assert "для 40001" in text
    assert "для 40002" in text
