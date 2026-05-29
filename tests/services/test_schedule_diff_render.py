from datetime import datetime, date
from zoneinfo import ZoneInfo

from src.bot.services.schedule_diff import (
    DayDiff,
    DiffSummary,
    render,
    _is_time_only_change,
    _format_groups,
)
from src.bot.services.schedule_service import ScheduleEvent

TZ = ZoneInfo("Europe/Moscow")


def _ev(hh, summary="A", kind="Лекция", location="", day=26):
    return ScheduleEvent(
        summary=summary, location=location,
        start=datetime(2026, 5, day, hh, 0, tzinfo=TZ),
        end=datetime(2026, 5, day, hh, 40, tzinfo=TZ),
        kind=kind,
    )


def _day(d=26, code="40001", added=None, removed=None, changed=None,
         old_events=None, new_events=None):
    """Утилита: собирает DayDiff с заполненными old_keys/new_keys."""
    added = added or []
    removed = removed or []
    changed = changed or []
    old_events = old_events or []
    new_events = new_events or []
    return DayDiff(
        date=date(2026, 5, d),
        group_code=code,
        added=list(added),
        removed=list(removed),
        changed=list(changed),
        old_keys=frozenset(e.key() for e in old_events),
        new_keys=frozenset(e.key() for e in new_events),
    )


# --- базовые случаи ---

def test_render_empty_summary_returns_none():
    assert render(DiffSummary(), known_groups=frozenset({"40001"})) is None


def test_render_appearance_short_header_only():
    text = render(DiffSummary(is_appearance=True), known_groups=frozenset({"40001"}))
    assert text == "🗓️ Появилось расписание!"


# --- формат строк ---

def test_render_added_to_empty_slot_uses_new_emoji():
    """Пара в пустой слот (без удаления в том же времени) → 🆕."""
    e = _ev(14, summary="Технология ООП", kind="Лекция")
    day = _day(added=[e], old_events=[], new_events=[e])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "🆕 14:00–14:40 · Лекция" in text
    assert "<b>Технология ООП</b>" in text


def test_render_added_over_removed_same_start_uses_check():
    """Замена предмета в том же слоте: старый ❌, новый ✅ (а не 🆕)."""
    old = _ev(14, summary="Программирование", kind="Лекция")
    new = _ev(14, summary="Технология ООП", kind="Лекция")
    day = _day(added=[new], removed=[old], old_events=[old], new_events=[new])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "✅ 14:00–14:40 · Лекция" in text
    assert "❌ 14:00–14:40 · Лекция" in text
    assert "🆕" not in text


def test_render_added_with_unrelated_removal_other_slot_uses_new():
    """Удаление в другом слоте не делает добавление заменой → остаётся 🆕."""
    added = _ev(18, summary="Иностранный язык", kind="Зачет")
    removed = _ev(14, summary="Химия", kind="Лекция")
    day = _day(
        added=[added], removed=[removed],
        old_events=[removed], new_events=[added],
    )
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "🆕 18:00–18:40 · Зачет" in text
    assert "❌ 14:00–14:40 · Лекция" in text


def test_render_removed_uses_cross_and_new_format():
    e = _ev(14, summary="Программирование", kind="Лекция")
    day = _day(removed=[e], old_events=[e], new_events=[])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "❌ 14:00–14:40 · Лекция" in text
    assert "<b>Программирование</b>" in text


def test_render_added_without_kind_omits_dot_separator():
    e = _ev(14, summary="Семинар", kind="")
    day = _day(added=[e], old_events=[], new_events=[e])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "🆕 14:00–14:40\n<b>Семинар</b>" in text
    time_line = next(ln for ln in text.splitlines() if "🆕" in ln)
    assert "·" not in time_line  # в строке времени нет точки-разделителя


def test_render_time_only_change_uses_alarm_clock():
    before = _ev(16, summary="ТООП", kind="Лекция")
    after = _ev(14, summary="ТООП", kind="Лекция")
    day = _day(changed=[(before, after)], old_events=[before], new_events=[after])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "⏰ 16:00–16:40 → 14:00–14:40 · Лекция" in text
    assert "<b>ТООП</b>" in text


def test_render_location_change_uses_pencil():
    before = ScheduleEvent(
        summary="A", location="ауд. 101", kind="Лекция",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 10, 40, tzinfo=TZ),
    )
    after = ScheduleEvent(
        summary="A", location="ауд. 202", kind="Лекция",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 10, 40, tzinfo=TZ),
    )
    day = _day(changed=[(before, after)], old_events=[before], new_events=[after])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "✏️" in text
    assert "⏰" not in text


def test_render_uses_en_dash_in_times():
    e = _ev(14)
    day = _day(added=[e], old_events=[], new_events=[e])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "14:00–14:40" in text  # en-dash
    assert "14:00-14:40" not in text  # не hyphen


def test_render_blank_line_between_pairs_in_same_day():
    e1 = _ev(10, summary="Первая")
    e2 = _ev(12, summary="Вторая")
    day = _day(added=[e1, e2], old_events=[], new_events=[e1, e2])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    # между двумя 🆕-блоками должна быть пустая строка
    assert "<b>Первая</b>\n\n🆕" in text


def test_render_blank_line_between_days():
    e1 = _ev(10, day=26)
    e2 = _ev(10, day=27)
    day1 = _day(d=26, added=[e1], old_events=[], new_events=[e1])
    day2 = _day(d=27, added=[e2], old_events=[], new_events=[e2])
    text = render(DiffSummary(days=[day1, day2]), known_groups=frozenset({"40001"}))
    # между блоками дней — пустая строка после закрытия blockquote
    assert "</blockquote>\n\n<b>" in text


def test_render_wraps_day_content_in_blockquote():
    """Содержимое блока дня обёрнуто в <blockquote>...</blockquote> (как в /пары и закрепе)."""
    e = _ev(14, summary="Технология ООП", kind="Лекция")
    day = _day(added=[e], old_events=[], new_events=[e])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "<blockquote>🆕 14:00–14:40 · Лекция\n<b>Технология ООП</b></blockquote>" in text


def test_render_escapes_html_in_summary():
    """Спецсимволы в summary эскейпятся (Telegram parse_mode=HTML)."""
    e = _ev(14, summary="A & B <C>", kind="Лекция")
    day = _day(added=[e], old_events=[], new_events=[e])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "<b>A &amp; B &lt;C&gt;</b>" in text
    assert "<b>A & B <C></b>" not in text


# --- кластеризация и суффиксы ---

def test_render_single_group_no_suffix():
    e = _ev(10)
    day = _day(code="40001", added=[e], old_events=[], new_events=[e])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert "для 40001" not in text


def test_render_full_cluster_no_suffix():
    """Две группы, идентичный (old, new) на дату — один блок без 'для …'."""
    before = _ev(16, summary="ТООП")
    after = _ev(14, summary="ТООП")
    day_a = _day(code="40001", changed=[(before, after)],
                 old_events=[before], new_events=[after])
    day_b = _day(code="40002", changed=[(before, after)],
                 old_events=[before], new_events=[after])
    text = render(DiffSummary(days=[day_a, day_b]),
                  known_groups=frozenset({"40001", "40002"}))
    assert "для 40001" not in text
    assert "для 40002" not in text
    # ровно один заголовок дня
    assert text.count("Во вторник") == 1  # 2026-05-26 — вторник


def test_render_partial_cluster_uses_suffix_for_two_of_three():
    """Три группы, у двух одинаковый diff, у третьей — другой."""
    before = _ev(16, summary="ТООП")
    after = _ev(14, summary="ТООП")
    other_before = _ev(10, summary="Другое")
    other_after = _ev(12, summary="Другое")
    day_a = _day(code="40001", changed=[(before, after)],
                 old_events=[before], new_events=[after])
    day_b = _day(code="40002", changed=[(before, after)],
                 old_events=[before], new_events=[after])
    day_c = _day(code="40003", changed=[(other_before, other_after)],
                 old_events=[other_before], new_events=[other_after])
    text = render(DiffSummary(days=[day_a, day_b, day_c]),
                  known_groups=frozenset({"40001", "40002", "40003"}))
    assert "для 40001 и 40002" in text
    assert "для 40003" in text


def test_render_each_group_own_diff_two_blocks_with_suffix():
    """Две группы, разные дифы — два блока с 'для …'."""
    e_a = _ev(10, summary="A")
    e_b = _ev(12, summary="B")
    day_a = _day(code="40001", added=[e_a], old_events=[], new_events=[e_a])
    day_b = _day(code="40002", added=[e_b], old_events=[], new_events=[e_b])
    text = render(DiffSummary(days=[day_a, day_b]),
                  known_groups=frozenset({"40001", "40002"}))
    assert "для 40001" in text
    assert "для 40002" in text


def test_render_was_same_became_different_two_blocks():
    """Было одинаковым, стало разным → два блока."""
    common = _ev(10, summary="Общая")
    only_a = _ev(12, summary="Только A")
    day_a = _day(
        code="40001",
        added=[only_a],
        old_events=[common],
        new_events=[common, only_a],
    )
    text = render(DiffSummary(days=[day_a]),
                  known_groups=frozenset({"40001", "40002"}))
    assert "для 40001" in text
    assert "для 40002" not in text  # 40002 без изменений в этом diff не упоминается


def test_render_header_starts_with_calendar_emoji():
    e = _ev(10)
    day = _day(added=[e], old_events=[], new_events=[e])
    text = render(DiffSummary(days=[day]), known_groups=frozenset({"40001"}))
    assert text.startswith("🗓️ Расписание обновилось\n\n")


# --- helpers (см. Task 3) ---

def test_is_time_only_change_true_when_only_start_end_differ():
    before = _ev(10, summary="A", kind="Лекция")
    after = _ev(12, summary="A", kind="Лекция")
    assert _is_time_only_change(before, after) is True


def test_is_time_only_change_false_when_location_differs():
    before = ScheduleEvent(
        summary="A", location="ауд. 101",
        start=datetime(2026, 5, 26, 10, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 10, 40, tzinfo=TZ),
        kind="Лекция",
    )
    after = ScheduleEvent(
        summary="A", location="ауд. 202",
        start=datetime(2026, 5, 26, 12, 0, tzinfo=TZ),
        end=datetime(2026, 5, 26, 12, 40, tzinfo=TZ),
        kind="Лекция",
    )
    assert _is_time_only_change(before, after) is False


def test_is_time_only_change_false_when_kind_differs():
    before = _ev(10, summary="A", kind="Лекция")
    after = _ev(10, summary="A", kind="Практика")
    assert _is_time_only_change(before, after) is False


def test_format_groups_one():
    assert _format_groups(["40001"]) == "40001"


def test_format_groups_two():
    assert _format_groups(["40001", "40002"]) == "40001 и 40002"


def test_format_groups_three():
    assert _format_groups(["40001", "40002", "40003"]) == "40001, 40002 и 40003"


def test_format_groups_sorted():
    assert _format_groups(["40002", "40001"]) == "40001 и 40002"
