"""Планировщик напоминаний: восстановление job'ов при старте, исполнение в момент Х."""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from aiogram import Bot

from src.config.settings import TIMEZONE, REMINDER_MISFIRE_HOURS
from src.bot.services.reminder_store import reminder_store
from src.bot.services import reminder_service as rs
from src.core.emoji import E

logger = logging.getLogger(__name__)


def classify_fire(fire_at: str, now: datetime, *, misfire_hours: int) -> str:
    """future — в будущем; late — просрочка ≤ порога; stale — просрочка больше порога."""
    dt = datetime.fromisoformat(fire_at)
    if dt >= now:
        return "future"
    overdue_h = (now - dt).total_seconds() / 3600
    return "late" if overdue_h <= misfire_hours else "stale"


def _job_id(reminder_id: int) -> str:
    return f"reminder:{reminder_id}"


class ReminderScheduler:
    def __init__(self, bot: Bot, *, store=reminder_store, misfire_hours: int = REMINDER_MISFIRE_HOURS):
        self.bot = bot
        self.store = store
        self.misfire_hours = misfire_hours
        self.scheduler = AsyncIOScheduler(
            timezone=TIMEZONE,
            job_defaults={"misfire_grace_time": 300, "coalesce": True},
        )

    async def start(self) -> None:
        await self.store.init()
        now = datetime.now(TIMEZONE)
        restored = late = stale = 0
        for rem in await self.store.list_all_pending():
            kind = classify_fire(rem["fire_at"], now, misfire_hours=self.misfire_hours)
            if kind == "future":
                self.schedule(rem["id"], rem["fire_at"])
                restored += 1
            elif kind == "late":
                await self._fire(rem["id"], late=True)
                late += 1
            else:
                await self.store.set_status(rem["id"], "fired")
                stale += 1
        self.scheduler.start()
        logger.info("Напоминания восстановлены: future=%s, late=%s, stale=%s", restored, late, stale)

    def schedule(self, reminder_id: int, fire_at: str) -> None:
        self.scheduler.add_job(
            self._fire, DateTrigger(run_date=datetime.fromisoformat(fire_at)),
            args=[reminder_id], id=_job_id(reminder_id), replace_existing=True)

    def unschedule(self, reminder_id: int) -> None:
        try:
            self.scheduler.remove_job(_job_id(reminder_id))
        except Exception:  # noqa: BLE001 — job мог не существовать
            pass

    async def _fire(self, reminder_id: int, *, late: bool = False) -> None:
        rem = await self.store.get(reminder_id)
        if not rem or rem["status"] != "pending":
            return
        late_note = None
        if late:
            dt = rs.parse_dt(rem["fire_at"])
            late_note = f"{E.ALARM_CLOCK} было запланировано на {dt:%H:%M}"
        subs = await self.store.list_subscribers(reminder_id) if rem["scope"] == "chat" else []
        target = rem["chat_id"]
        chunks = rs.render_ping(rem, subs, late_note=late_note)
        delivered = False
        for chunk in chunks:
            try:
                await self.bot.send_message(target, chunk, parse_mode="HTML",
                                            disable_web_page_preview=True)
                delivered = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось отправить напоминание %s: %s", reminder_id, exc)
        if delivered:
            await self.store.set_status(reminder_id, "fired")
        else:
            logger.warning("Напоминание %s не доставлено ни одним сообщением — "
                           "оставляю pending до следующего рестарта", reminder_id)

    def stop(self) -> None:
        self.scheduler.shutdown()


def start_reminder_scheduler(bot: Bot) -> "ReminderScheduler":
    scheduler = ReminderScheduler(bot)
    return scheduler
