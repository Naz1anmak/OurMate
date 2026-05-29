from datetime import date
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.bot.scheduler import schedule_scheduler as mod
from src.bot.scheduler.schedule_scheduler import ScheduleScheduler


def _patch_service(monkeypatch, *, effective, day_label, title, events):
    """Подменяет методы schedule_service для изоляции _daily_classes."""
    monkeypatch.setattr(
        mod.schedule_service, "get_effective_date_with_titles",
        lambda tz: (effective, day_label, title),
    )
    monkeypatch.setattr(
        mod.schedule_service, "get_classes_for_date",
        lambda d: events if d == effective else [],
    )
    monkeypatch.setattr(
        mod.schedule_service, "format_day_block",
        lambda d, base_title, icon_common: f"[{base_title}]",
    )


@pytest.mark.asyncio
async def test_cron_job_runs_refresh_then_sends_diff_then_daily_classes(monkeypatch):
    bot = AsyncMock()
    sched = ScheduleScheduler(bot)

    refresher = AsyncMock()
    refresh_result = MagicMock(diff_message="🗓️ Расписание обновилось\n...")
    refresher.force_refresh = AsyncMock(return_value=refresh_result)
    sched.refresher = refresher

    sched._daily_classes = AsyncMock()

    await sched._cron_job()
    refresher.force_refresh.assert_called_once_with("cron:broadcast")
    bot.send_message.assert_called_once()
    args, kwargs = bot.send_message.call_args
    assert "Расписание обновилось" in args[1] or "Расписание обновилось" in kwargs.get("text", "")
    sched._daily_classes.assert_called_once()


@pytest.mark.asyncio
async def test_cron_job_without_diff_skips_send_message():
    bot = AsyncMock()
    sched = ScheduleScheduler(bot)
    refresher = AsyncMock()
    refresher.force_refresh = AsyncMock(return_value=MagicMock(diff_message=None))
    sched.refresher = refresher
    sched._daily_classes = AsyncMock()

    await sched._cron_job()
    bot.send_message.assert_not_called()
    sched._daily_classes.assert_called_once()


@pytest.mark.asyncio
async def test_daily_classes_morning_sends_today(monkeypatch):
    """Утром (effective_date = сегодня, пары есть) → «Пары на сегодня»."""
    bot = AsyncMock()
    sched = ScheduleScheduler(bot)
    _patch_service(
        monkeypatch, effective=date(2026, 5, 29),
        day_label="сегодня", title="Пары на сегодня", events=["ev"],
    )
    await sched._daily_classes()
    bot.send_message.assert_called_once()
    args, _ = bot.send_message.call_args
    assert "Пары на сегодня" in args[1]


@pytest.mark.asyncio
async def test_daily_classes_evening_rolls_to_tomorrow(monkeypatch):
    """Вечером, после последней пары (effective_date = завтра) → «Пары на завтра»."""
    bot = AsyncMock()
    sched = ScheduleScheduler(bot)
    _patch_service(
        monkeypatch, effective=date(2026, 5, 30),
        day_label="завтра", title="Пары на завтра", events=["ev"],
    )
    await sched._daily_classes()
    bot.send_message.assert_called_once()
    args, _ = bot.send_message.call_args
    assert "Пары на завтра" in args[1]


@pytest.mark.asyncio
async def test_daily_classes_silent_when_no_events(monkeypatch):
    """В актуальный день пар нет → рассылка молчит."""
    bot = AsyncMock()
    sched = ScheduleScheduler(bot)
    _patch_service(
        monkeypatch, effective=date(2026, 5, 31),
        day_label="сегодня", title="Пары на сегодня", events=[],
    )
    await sched._daily_classes()
    bot.send_message.assert_not_called()
