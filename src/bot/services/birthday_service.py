"""
Сервис для работы с днями рождения.
Содержит логику для поиска именинников и генерации поздравлений.
"""

from typing import List, Optional
from zoneinfo import ZoneInfo

from src.models.user import User
from src.utils.date_utils import today_mmdd, get_next_birthday, format_birthday_date
from src.utils.text_utils import load_birthdays, build_mention_list
from src.bot.services.llm_service import LLMService
from src.config.settings import PROMPT_TEMPLATE_BIRTHDAY


class BirthdayService:
    """
    Сервис для работы с днями рождения пользователей.
    Загружает данные, находит именинников и генерирует поздравления.
    """
    
    def __init__(self):
        # Загружаем список пользователей при инициализации
        self.users = load_birthdays()
    
    def get_todays_birthdays(self, timezone: ZoneInfo) -> List[User]:
        """
        Получает список пользователей, у которых сегодня день рождения.
        
        Args:
            timezone (ZoneInfo): Часовой пояс для определения текущей даты
            
        Returns:
            List[User]: Список именинников
        """
        today = today_mmdd(timezone)
        return [user for user in self.users if user.birthday == today]
    
    def get_next_birthday_user(self, timezone: ZoneInfo) -> Optional[User]:
        """
        Получает пользователя с ближайшим днем рождения.
        
        Args:
            timezone (ZoneInfo): Часовой пояс
            
        Returns:
            Optional[User]: Пользователь с ближайшим днем рождения или None
        """
        today = today_mmdd(timezone)
        return get_next_birthday(self.users, today)
    
    def generate_birthday_message(self, users: List[User]) -> str:
        """
        Генерирует поздравление для именинников.
        
        Args:
            users (List[User]): Список именинников
            
        Returns:
            str: Сгенерированное поздравление
        """
        if not users:
            return ""
        
        # Создаем список упоминаний
        mentions = build_mention_list(users)
        
        # Формируем промпт для LLM
        prompt = PROMPT_TEMPLATE_BIRTHDAY.format(mentions=mentions)
        
        # Генерируем поздравление через LLM
        return LLMService.send_birthday_request(prompt)
    
    def get_next_birthday_notification(self, timezone: ZoneInfo) -> Optional[str]:
        """
        Создает уведомление о следующем дне рождения.
        
        Args:
            timezone (ZoneInfo): Часовой пояс
            
        Returns:
            Optional[str]: Текст уведомления или None, если нет данных
        """
        next_user = self.get_next_birthday_user(timezone)
        if not next_user:
            return None
        
        # Находим всех пользователей с этим днем рождения
        same_birthday_users = [
            user for user in self.users 
            if user.birthday == next_user.birthday
        ]
        
        # Формируем список упоминаний
        mentions = build_mention_list(same_birthday_users)
        
        # Форматируем дату
        formatted_date = format_birthday_date(next_user.birthday)
        
        return f"Следующий день рождения — {formatted_date}:\n{mentions}"
    
    def reload_users(self) -> None:
        """
        Перезагружает список пользователей из файла.
        Полезно, если данные были изменены во время работы бота.
        """
        self.users = load_birthdays()


# Создаем глобальный экземпляр сервиса дней рождения
birthday_service = BirthdayService()
