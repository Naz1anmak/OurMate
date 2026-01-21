"""
Планировщик дней рождения.
Содержит логику для автоматической отправки поздравлений и уведомлений.
"""
import asyncio
import logging
from pathlib import Path
import json
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
ACTIVE_USERS_CACHE_FILE = Path("data/cache/active_users_snapshot.json")

def _format_user(user) -> str:
    username = f"@{user.username}" if user.username else None
    return f"{username}({user.user_id})" if username else str(user.user_id)

def _format_user_tuple(user_id: int, username: str | None) -> str:
    username_part = f"@{username}" if username else None
    return f"{username_part}({user_id})" if username_part else str(user_id)

def _load_active_snapshot() -> dict[int, str | None]:
    try:
        if not ACTIVE_USERS_CACHE_FILE.exists():
            return {}
        data = json.loads(ACTIVE_USERS_CACHE_FILE.read_text(encoding="utf-8"))
        return {int(item["user_id"]): item.get("username") for item in data}
    except Exception:
        return {}

def _save_active_snapshot(users: list) -> None:
    try:
        ACTIVE_USERS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"user_id": u.user_id, "username": u.username}
            for u in users
            if u.user_id is not None and u.interacted_with_bot
        ]
        ACTIVE_USERS_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

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

        if not_interacted:
            logger.info(
                "Пропущены поздравления. Не активировали бота: %s",
                len(not_interacted),
            )
        return False
    
    async def _notify_next_birthday(self):
        """
        Отправляет уведомление о ближайшем дне рождения владельцу бота в ЛС.
        Выполняется один раз при запуске.
        """
        notification = birthday_service.get_next_birthday_notification(TIMEZONE)
        if not notification:
            return
        try:
            await self.bot.send_message(
                OWNER_CHAT_ID,
                notification,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось отправить уведомление о ближайшем ДР владельцу: %s", exc)
    
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
        failures = 0
        failure_samples: list[str] = []
        for user in birthday_service.users:
            if user.user_id is None:
                continue
            checked += 1
            try:
                chat = await self.bot.get_chat(user.user_id)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                if len(failure_samples) < 3:
                    failure_samples.append(f"user_id={user.user_id}: {exc}")
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
        total = len(birthday_service.users)  # учитываем всех, даже без user_id
        details = f" ({' | '.join(updated_users)})" if updated_users else ""
        logger.info(
            "Обновлены логины: %s/%s/%s%s; ошибки: %s",
            len(updated_users),
            filled,
            total,
            details,
            failures,
        )
        if failures and failure_samples:
            logger.warning("Примеры ошибок при обновлении логинов: %s", "; ".join(failure_samples))

    async def _refresh_access_flags(self) -> None:
        """Обновляет interacted_with_bot по факту доступности пользователя для бота."""
        changed = False
        deactivated = []
        total_users = 0
        snapshot_before = _load_active_snapshot()
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
                    deactivated.append(user)
            else:
                # Не включаем обратно автоматически
                pass
        if changed:
            birthday_service.save_users()
        active_users_now = [u for u in birthday_service.users if u.user_id is not None and u.interacted_with_bot]
        active_count = len(active_users_now)

        activated = []
        for u in active_users_now:
            if u.user_id not in snapshot_before:
                activated.append(u)
        deactivated_for_delta = []
        for uid, uname in snapshot_before.items():
            if all(u.user_id != uid for u in active_users_now):
                deactivated_for_delta.append((uid, uname))

        delta_parts: list[str] = []
        if activated:
            delta_parts.append(" | ".join("+" + _format_user(u) for u in activated))
        if deactivated or deactivated_for_delta:
            combined: list[str] = []
            seen: set[int] = set()
            for uid, uname in deactivated_for_delta:
                if uid in seen:
                    continue
                seen.add(uid)
                combined.append("-" + _format_user_tuple(uid, uname))
            for u in deactivated:
                if u.user_id in seen:
                    continue
                seen.add(u.user_id)
                combined.append("-" + _format_user(u))
            if combined:
                delta_parts.append(" | ".join(combined))

        changes = f" ({' | '.join(delta_parts)})" if delta_parts else ""
        logger.info("Подписаны на поздравления: %s/%s%s", active_count, total_users, changes)

        _save_active_snapshot(active_users_now)

    async def _daily_check(self):
        """
        Ежедневная проверка: если сегодня есть ДР — поздравить в беседе.
        После проверки отправляем владельцу уведомление о следующем ДР независимо от того,
        было ли поздравление (чтобы помнить о ближайшей дате даже без активации пользователей).
        """
        await self._refresh_usernames()
        await self._refresh_access_flags()
        todays_birthdays = birthday_service.get_todays_birthdays(TIMEZONE)
        if todays_birthdays:
            await self._send_birthday_greeting(todays_birthdays)
            # Сообщаем владельцу о следующем ДР даже если поздравление не отправилось
            await self._notify_next_birthday()
    
    def stop(self):
        """
        Останавливает планировщик.
        """
        self.scheduler.shutdown()

def start_birthday_scheduler(bot: Bot):
    """Запускает планировщик дней рождения."""
    scheduler = BirthdayScheduler(bot)
    scheduler.start()
    return scheduler
