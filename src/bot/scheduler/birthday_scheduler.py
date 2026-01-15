"""
Планировщик дней рождения.
Содержит логику для автоматической отправки поздравлений и уведомлений.
"""

import asyncio
import logging
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from aiogram.enums import ChatAction

from src.config.settings import (
    TIMEZONE,
    SEND_HOUR,
    SEND_MINUTE,
    CHAT_ID,
    OWNER_CHAT_ID,
    LAST_BIRTHDAY_GREETING_FILE,
)
from src.bot.services.birthday_service import birthday_service
from src.utils.date_utils import today_mmdd


logger = logging.getLogger(__name__)


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
        self.last_greeting_file = Path(LAST_BIRTHDAY_GREETING_FILE)
    
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
    
    def _get_last_greeting_date(self) -> str:
        """
        Читает дату последнего поздравления из файла.
        
        Returns:
            str: Дата в формате D.M или пустая строка, если файла нет
        """
        if self.last_greeting_file.exists():
            return self.last_greeting_file.read_text().strip()
        return ""
    
    def _save_greeting_date(self, date_str: str) -> None:
        """
        Сохраняет дату поздравления в файл.
        
        Args:
            date_str (str): Дата в формате D.M
        """
        self.last_greeting_file.parent.mkdir(parents=True, exist_ok=True)
        self.last_greeting_file.write_text(date_str)
    
    async def _send_birthday_greeting(self, todays_birthdays) -> bool:
        """
        Отправляет поздравление для пользователей, взаимодействовавших с ботом.
        Пользователей без взаимодействия игнорирует.
        
        Args:
            todays_birthdays: Список всех именинников
            
        Returns:
            bool: True, если поздравление было отправлено, False — если уже поздравляли сегодня
        """
        today = today_mmdd(TIMEZONE)
        
        # Проверяем, не поздравляли ли уже сегодня
        if self._get_last_greeting_date() == today:
            return False  # Уже поздравили сегодня
        
        # Генерируем поздравления (только для взаимодействовавших)
        try:
            greetings, not_interacted = birthday_service.generate_birthday_messages(todays_birthdays)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось сгенерировать поздравление: %s", exc, exc_info=True)
            return False
        
        if greetings:
            for greeting in greetings:
                await self.bot.send_message(
                    CHAT_ID,
                    greeting,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            self._save_greeting_date(today)  # Сохраняем дату отправки
            return True
        return False
    
    async def _notify_next_birthday(self):
        """
        Отправляет уведомление о ближайшем дне рождения владельцу бота в ЛС.
        Выполняется один раз при запуске.
        """
        notification = birthday_service.get_next_birthday_notification(TIMEZONE)
        if notification:
            await self.bot.send_message(
                OWNER_CHAT_ID,
                notification,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    
    async def _on_startup_check(self):
        """
        При запуске: отправить поздравления, если сегодня есть ДР и еще не поздравляли,
        и уведомить владельца о следующем ДР.
        """
        await self._refresh_usernames()
        await self._refresh_access_flags()
        todays_birthdays = birthday_service.get_todays_birthdays(TIMEZONE)
        if todays_birthdays:
            await self._send_birthday_greeting(todays_birthdays)
        
        # При запуске всегда отправляем информацию о следующем ДР
        await self._notify_next_birthday()

    async def _refresh_usernames(self) -> None:
        """Обновляет usernames при старте бота, где доступно по user_id."""
        updated_users: list[str] = []
        checked = 0
        for user in birthday_service.users:
            if user.user_id is None:
                continue
            checked += 1
            try:
                chat = await self.bot.get_chat(user.user_id)
            except Exception:
                continue
            username = getattr(chat, "username", None)
            if username and username != user.username:
                before = user.username or "null"
                after = username
                user.username = username
                updated_users.append(f"{before} -> {after}")
        if updated_users:
            birthday_service.save_users()
        filled = sum(1 for user in birthday_service.users if user.username)
        total = sum(1 for user in birthday_service.users if user.user_id is not None)
        details = f" ({' и '.join(updated_users)})" if updated_users else ""
        logger.info("Обновлены логины: %s/%s/%s%s", len(updated_users), filled, total, details)

    async def _refresh_access_flags(self) -> None:
        """Обновляет interacted_with_bot по факту доступности пользователя для бота."""
        changed = False
        deactivated = []
        total_users = 0
        for user in birthday_service.users:
            if user.user_id is None:
                continue
            total_users += 1
            try:
                # Неблокирующий пинг: если бот заблокирован, получим исключение
                await self.bot.send_chat_action(user.user_id, action=ChatAction.TYPING)
            except Exception:
                if user.interacted_with_bot:
                    user.interacted_with_bot = False
                    changed = True
                    deactivated.append(user.user_id)
            else:
                # Не включаем обратно: активация только вручную/через ЛС
                pass
        if changed:
            birthday_service.save_users()
        active_count = sum(
            1 for u in birthday_service.users if u.user_id is not None and u.interacted_with_bot
        )
        logger.info("Подписаны на поздравления: %s/%s", active_count, total_users)

    async def _daily_check(self):
        """
        Ежедневная проверка: если сегодня есть ДР — поздравить в беседе.
        Если сегодня есть ДР — после поздравления уведомить владельца о следующем ДР.
        Ничего не слать владельцу, если ДР нет (во избежание дублирования информации).
        """
        await self._refresh_usernames()
        await self._refresh_access_flags()
        todays_birthdays = birthday_service.get_todays_birthdays(TIMEZONE)
        if todays_birthdays:
            was_sent = await self._send_birthday_greeting(todays_birthdays)
            # После поздравления сообщаем владельцу о следующем ДР
            if was_sent:
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
