"""
Планировщик для ежедневного уведомления о парах.
"""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from src.config.settings import TIMEZONE, CHAT_ID, SCHEDULE_SEND_HOUR, SCHEDULE_SEND_MINUTE
from src.bot.services.schedule_service import schedule_service

class ScheduleScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    def start(self):
        self.scheduler.add_job(
            self._daily_classes,
            CronTrigger(hour=SCHEDULE_SEND_HOUR, minute=SCHEDULE_SEND_MINUTE, timezone=TIMEZONE),
        )
        self.scheduler.start()

    async def _daily_classes(self):
        events = schedule_service.get_todays_classes(TIMEZONE)
        if events:
            text = schedule_service.format_classes(events, "📚 Пары на сегодня:", "")
            await self.bot.send_message(CHAT_ID, text)

    def stop(self):
        self.scheduler.shutdown()

def start_schedule_scheduler(bot: Bot):
    scheduler = ScheduleScheduler(bot)
    scheduler.start()
    return scheduler
