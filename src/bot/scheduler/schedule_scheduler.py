"""
Планировщик для ежедневного уведомления о парах.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from src.config.settings import TIMEZONE, CHAT_ID, SCHEDULE_SEND_HOUR, SCHEDULE_SEND_MINUTE, SCHEDULE_BROADCAST_ENABLED
from src.bot.services.schedule_service import schedule_service
from src.core.emoji import E

logger = logging.getLogger(__name__)


class ScheduleScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.refresher = None  # инжектится в setup.py
        self.scheduler = AsyncIOScheduler(
            timezone=TIMEZONE,
            job_defaults={"misfire_grace_time": 300, "coalesce": True},
        )

    def start(self):
        if not SCHEDULE_BROADCAST_ENABLED:
            return
        self.scheduler.add_job(
            self._cron_job,
            CronTrigger(hour=SCHEDULE_SEND_HOUR, minute=SCHEDULE_SEND_MINUTE, timezone=TIMEZONE),
        )
        self.scheduler.start()

    async def _cron_job(self):
        if self.refresher is not None:
            try:
                result = await self.refresher.force_refresh("cron:broadcast")
                if result.diff_message:
                    await self.bot.send_message(
                        CHAT_ID, result.diff_message,
                        parse_mode="HTML", disable_web_page_preview=True,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("cron:broadcast refresh упал: %s", exc)
        await self._daily_classes()

    async def _daily_classes(self):
        today = datetime.now(TIMEZONE).date()
        events = schedule_service.get_classes_for_date(today)
        if events:
            text = schedule_service.format_day_block(today, "Пары на сегодня", icon_common=str(E.NO_CLASS_BOOKS))
            await self.bot.send_message(CHAT_ID, text, parse_mode="HTML")

    def stop(self):
        self.scheduler.shutdown()


def start_schedule_scheduler(bot: Bot):
    scheduler = ScheduleScheduler(bot)
    scheduler.start()
    return scheduler
