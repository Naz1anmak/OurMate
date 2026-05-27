from unittest.mock import AsyncMock, MagicMock
import pytest

from src.bot.scheduler.pinned_schedule_scheduler import PinnedScheduleScheduler


@pytest.mark.asyncio
async def test_pinned_cron_job_refresh_then_diff_then_render():
    bot = AsyncMock()
    sched = PinnedScheduleScheduler(bot)
    refresher = AsyncMock()
    refresher.force_refresh = AsyncMock(return_value=MagicMock(diff_message="🗓️ ..."))
    sched.refresher = refresher
    sched._update_pinned_message = AsyncMock()

    await sched._cron_job()
    refresher.force_refresh.assert_called_once_with("cron:pinned")
    bot.send_message.assert_called_once()
    sched._update_pinned_message.assert_called_once()


@pytest.mark.asyncio
async def test_update_now_calls_update_pinned_without_refresh():
    bot = AsyncMock()
    sched = PinnedScheduleScheduler(bot)
    refresher = AsyncMock()
    sched.refresher = refresher
    sched._update_pinned_message = AsyncMock()

    await sched.update_now()
    sched._update_pinned_message.assert_called_once()
    refresher.force_refresh.assert_not_called()
