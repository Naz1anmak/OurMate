from unittest.mock import AsyncMock, MagicMock
import pytest

from src.bot.scheduler.schedule_scheduler import ScheduleScheduler


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
