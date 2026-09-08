from datetime import datetime, date
from zoneinfo import ZoneInfo

from src.bot.services.schedule_diff import compute_diff, DiffSummary
from src.bot.services.schedule_service import ScheduleEvent

TZ = ZoneInfo("Europe/Moscow")


def _ev(day_d, hh, summary="A", kind="Лекция", location=""):
    return ScheduleEvent(
        summary=summary, location=location,
        start=datetime(2026, 5, day_d, hh, 0, tzinfo=TZ),
        end=datetime(2026, 5, day_d, hh, 40, tzinfo=TZ),
        kind=kind,
    )


def test_compute_diff_added_pairs():
    old = {"GRP_A": []}
    new = {"GRP_A": [_ev(26, 10)]}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.is_appearance is True


def test_compute_diff_removed_pair():
    e = _ev(26, 10)
    old = {"GRP_A": [e]}
    new = {"GRP_A": []}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.is_appearance is False
    assert len(summary.days) == 1
    assert summary.days[0].removed == [e]


def test_compute_diff_changed_pair_same_summary_diff_time():
    old = {"GRP_A": [_ev(26, 10, summary="A")]}
    new = {"GRP_A": [_ev(26, 12, summary="A")]}  # время сменилось
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert len(summary.days) == 1
    assert len(summary.days[0].changed) == 1


def test_compute_diff_skips_past_dates():
    old = {"GRP_A": [_ev(20, 10)]}  # 2026-05-20 < from_date
    new = {"GRP_A": []}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.days == []
    assert summary.is_appearance is False


def test_appearance_requires_all_groups_to_appear():
    """Если одна группа имела пары — это не appearance."""
    e = _ev(26, 10)
    old = {"GRP_A": [e], "GRP_B": []}
    new = {"GRP_A": [e, _ev(27, 10)], "GRP_B": [_ev(26, 12)]}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.is_appearance is False


def test_no_diff_returns_empty_summary():
    e = _ev(26, 10)
    old = {"GRP_A": [e]}
    new = {"GRP_A": [e]}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.days == []
    assert summary.is_appearance is False


def test_day_diff_carries_keys_for_clustering():
    """DayDiff содержит множества key() событий до и после — для кластеризации в render."""
    before = _ev(26, 10, summary="A")
    after = _ev(26, 12, summary="A")
    old = {"GRP_A": [before]}
    new = {"GRP_A": [after]}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert len(summary.days) == 1
    day = summary.days[0]
    assert day.old_keys == frozenset({before.key()})
    assert day.new_keys == frozenset({after.key()})


def test_day_diff_keys_are_per_date_not_all_events():
    """Если на дату событие одно, old_keys/new_keys содержат только его ключ."""
    e1 = _ev(26, 10, summary="A")
    e2 = _ev(27, 14, summary="B")  # другой день
    old = {"GRP_A": [e1, e2]}
    new = {"GRP_A": [e2]}  # удалили e1
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    day_26 = next(d for d in summary.days if d.date == date(2026, 5, 26))
    assert day_26.old_keys == frozenset({e1.key()})
    assert day_26.new_keys == frozenset()
