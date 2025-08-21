"""
Планировщик дней рождения.
Содержит логику для автоматической отправки поздравлений и уведомлений.
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from src.config.settings import TIMEZONE, SEND_HOUR, SEND_MINUTE, CHAT_ID, OWNER_CHAT_ID
from src.bot.services.birthday_service import birthday_service


class BirthdayScheduler:
    """
    Планировщик для автоматической отправки поздравлений с днями рождения.
    Запускает задачи при старте бота и по расписанию.
    """
    
    def __init__(self, bot: Bot):
        """
        Инициализирует планировщик.
        
        Args:
            bot (Bot): Экземпляр бота для отправки сообщений
        """
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    
    def start(self):
        """
        Запускает планировщик и выполняет начальные задачи.
        """
        # При старте: поздравить, если сегодня ДР, и в ЛС прислать только следующего ДР
        loop = asyncio.get_event_loop()
        loop.create_task(self._on_startup_check())
        
        # Настраиваем ежедневное расписание
        self.scheduler.add_job(
            self._daily_check,
            CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE)
        )
        
        # Запускаем планировщик
        self.scheduler.start()
    
    async def _notify_next_birthday(self):
        """
        Отправляет уведомление о ближайшем дне рождения владельцу бота.
        Выполняется один раз при запуске.
        """
        notification = birthday_service.get_next_birthday_notification(TIMEZONE)
        if notification:
            await self.bot.send_message(OWNER_CHAT_ID, notification)
    
    async def _on_startup_check(self):
        """
        При запуске: отправить поздравления, если сегодня есть ДР, и уведомить владельца
        о следующем ДР (даже если сегодня есть именинники).
        """
        todays_birthdays = birthday_service.get_todays_birthdays(TIMEZONE)
        if todays_birthdays:
            greeting = birthday_service.generate_birthday_message(todays_birthdays)
            if greeting:
                await self.bot.send_message(CHAT_ID, greeting)
        await self._notify_next_birthday()

    async def _daily_check(self):
        """
        Ежедневная проверка: если сегодня есть ДР — поздравить в беседе.
        Если сегодня есть ДР — после поздравления уведомить владельца о следующем ДР.
        Ничего не слать владельцу, если ДР нет (во избежание дублирования информации).
        """
        todays_birthdays = birthday_service.get_todays_birthdays(TIMEZONE)
        if todays_birthdays:
            greeting = birthday_service.generate_birthday_message(todays_birthdays)
            if greeting:
                await self.bot.send_message(CHAT_ID, greeting)
            # После поздравления сообщаем владельцу о следующем ДР
            await self._notify_next_birthday()
    
    def stop(self):
        """
        Останавливает планировщик.
        """
        self.scheduler.shutdown()


def start_scheduler(bot: Bot):
    """
    Функция для запуска планировщика (для обратной совместимости).
    
    Args:
        bot (Bot): Экземпляр бота
    """
    scheduler = BirthdayScheduler(bot)
    scheduler.start()
    return scheduler
