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
    old = {"40001": []}
    new = {"40001": [_ev(26, 10)]}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.is_appearance is True


def test_compute_diff_removed_pair():
    e = _ev(26, 10)
    old = {"40001": [e]}
    new = {"40001": []}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.is_appearance is False
    assert len(summary.days) == 1
    assert summary.days[0].removed == [e]


def test_compute_diff_changed_pair_same_summary_diff_time():
    old = {"40001": [_ev(26, 10, summary="A")]}
    new = {"40001": [_ev(26, 12, summary="A")]}  # время сменилось
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert len(summary.days) == 1
    assert len(summary.days[0].changed) == 1


def test_compute_diff_skips_past_dates():
    old = {"40001": [_ev(20, 10)]}  # 2026-05-20 < from_date
    new = {"40001": []}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.days == []
    assert summary.is_appearance is False


def test_appearance_requires_all_groups_to_appear():
    """Если одна группа имела пары — это не appearance."""
    e = _ev(26, 10)
    old = {"40001": [e], "40002": []}
    new = {"40001": [e, _ev(27, 10)], "40002": [_ev(26, 12)]}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.is_appearance is False


def test_no_diff_returns_empty_summary():
    e = _ev(26, 10)
    old = {"40001": [e]}
    new = {"40001": [e]}
    summary = compute_diff(old, new, from_date=date(2026, 5, 26))
    assert summary.days == []
    assert summary.is_appearance is False
