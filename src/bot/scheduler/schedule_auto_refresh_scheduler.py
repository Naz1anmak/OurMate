"""
Планировщик дополнительных проверок обновлений расписания в течение дня.
"""
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.settings import CHAT_ID, TIMEZONE, SCHEDULE_AUTO_REFRESH_HOURS

logger = logging.getLogger(__name__)


class ScheduleAutoRefreshScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.refresher = None       # инжектится в main.py
        self.pinned_scheduler = None  # инжектится в main.py (опционально)
        self.scheduler = AsyncIOScheduler(
            timezone=TIMEZONE,
            job_defaults={"misfire_grace_time": 300, "coalesce": True},
        )

    def start(self):
        if not SCHEDULE_AUTO_REFRESH_HOURS:
            logger.info("Доп. проверки расписания: список часов пуст, отключено")
            return

        for hour in SCHEDULE_AUTO_REFRESH_HOURS:
            self.scheduler.add_job(
                self._refresh_job,
                CronTrigger(hour=hour, minute=0, timezone=TIMEZONE),
            )

        self.scheduler.start()
        logger.info(
            "Доп. проверки расписания запланированы на %s",
            [f"{h:02d}:00" for h in SCHEDULE_AUTO_REFRESH_HOURS],
        )

    async def _refresh_job(self):
        if self.refresher is None:
            return
        try:
            result = await self.refresher.force_refresh("cron:auto_refresh")
            if result.diff_message:
                await self.bot.send_message(
                    CHAT_ID, result.diff_message,
                    parse_mode="HTML", disable_web_page_preview=True,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cron:auto_refresh упал: %s", exc)
            return

        if self.pinned_scheduler is not None:
            try:
                await self.pinned_scheduler.update_now()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cron:auto_refresh обновление закрепа упало: %s", exc)

    def stop(self):
        self.scheduler.shutdown()


def start_schedule_auto_refresh_scheduler(bot: Bot) -> "ScheduleAutoRefreshScheduler":
    scheduler = ScheduleAutoRefreshScheduler(bot)
    scheduler.start()
    return scheduler
