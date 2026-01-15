"""
Сервис для работы с днями рождения.
Содержит логику для поиска именинников и генерации поздравлений.
"""

from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from src.models.user import User
from src.utils.date_utils import today_mmdd, get_next_birthday, parse_day_month
from src.utils.text_utils import load_birthdays, build_mention_list, build_mention_list_for_prompt, save_birthdays
from src.bot.services.llm_service import LLMService
from src.config.settings import (
    PROMPT_TEMPLATE_BIRTHDAY_ACTIVE,
    PROMPT_TEMPLATE_BIRTHDAY_FORMER,
)


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
        now_str = today_mmdd(timezone)
        today_day, today_month = parse_day_month(now_str)

        todays_users: List[User] = []
        for user in self.users:
            try:
                day, month = parse_day_month(user.birthday)
                if day == today_day and month == today_month:
                    todays_users.append(user)
            except ValueError:
                continue
        return todays_users

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
    
    def _split_by_status(self, users: List[User]):
        active = [u for u in users if u.status != "-"]
        former = [u for u in users if u.status == "-"]
        return active, former

    def generate_birthday_messages(self, users: List[User]) -> tuple[List[str], List[User]]:
        """
        Генерирует поздравления для пользователей, взаимодействовавших с ботом.
        Создаёт отдельное поздравление для каждого активного/отчисленного пользователя.
        
        Returns:
            tuple[List[str], List[User]]: (сообщения для отправки, пользователи без взаимодействия)
        """
        if not users:
            return [], []

        # Разделяем на взаимодействовавших и не взаимодействовавших
        interacted = [u for u in users if u.interacted_with_bot]
        not_interacted = [u for u in users if not u.interacted_with_bot]

        if not interacted:
            return [], not_interacted

        active, former = self._split_by_status(interacted)
        messages: List[str] = []

        # Создаём отдельное поздравление для каждого активного пользователя
        if active:
            template = PROMPT_TEMPLATE_BIRTHDAY_ACTIVE
            if template:
                for user in active:
                    prompt = template.format(mentions=user.name)
                    msg = LLMService.send_birthday_request(prompt)
                    if msg:
                        messages.append(self._enrich_mentions(msg, [user]))

        # Создаём отдельное поздравление для каждого отчисленного пользователя
        if former:
            template = PROMPT_TEMPLATE_BIRTHDAY_FORMER or PROMPT_TEMPLATE_BIRTHDAY_ACTIVE
            if template:
                for user in former:
                    prompt = template.format(mentions=user.name)
                    msg = LLMService.send_birthday_request(prompt)
                    if msg:
                        messages.append(self._enrich_mentions(msg, [user]))

        return messages, not_interacted

    @staticmethod
    def _enrich_mentions(text: str, users: List[User]) -> str:
        """Заменяет @id<user_id>, @Имя или Имя на кликабельную ссылку."""
        result = text
        for user in users:
            if user.user_id is None:
                continue
            anchor = user.mention_html()
            at_name = f"@{user.name}"
            at_id = f"@id{user.user_id}"

            if anchor in result:
                continue
            if at_id in result:
                result = result.replace(at_id, anchor, 1)
                result = result.replace(f"{anchor} {user.name}", anchor)
                continue
            if at_name in result:
                result = result.replace(at_name, anchor)
                continue
            if user.name in result:
                result = result.replace(user.name, anchor, 1)
        return result
    
    def get_next_birthday_notification(self, timezone: ZoneInfo) -> Optional[str]:
        """
        Создает уведомление о следующем дне рождения для ЛС владельца.
        Формат: "Следующий день рождения:\nИван Иванович, Петр Петрович и Сергей Сергеевич — 20 января"
        
        Args:
            timezone (ZoneInfo): Часовой пояс
            
        Returns:
            Optional[str]: Текст уведомления или None, если нет данных
        """
        next_user = self.get_next_birthday_user(timezone)
        if not next_user:
            return None
        
        # Находим ВСЕХ пользователей с этим днем рождения
        same_birthday_users = []
        try:
            target_day, target_month = parse_day_month(next_user.birthday)
        except ValueError:
            target_day, target_month = None, None

        for user in self.users:
            try:
                day, month = parse_day_month(user.birthday)
                if day == target_day and month == target_month:
                    same_birthday_users.append(user)
            except ValueError:
                continue
        
        # Если список пустой, используем next_user
        users_to_mention = same_birthday_users if same_birthday_users else [next_user]
        
        # Получаем дату СЛЕДУЮЩЕГО дня рождения
        today = datetime.now(timezone).date()
        try:
            day, month = parse_day_month(next_user.birthday)
            # Ищем следующее наступление этого дня/месяца
            next_year_birthday = date(today.year, month, day)
            if next_year_birthday <= today:
                next_year_birthday = date(today.year + 1, month, day)
            # Форматируем дату: "20 января"
            formatted_date = next_year_birthday.strftime("%d %B").lstrip('0')
            # Переводим месяц на русский
            months_ru = {
                "January": "января", "February": "февраля", "March": "марта",
                "April": "апреля", "May": "мая", "June": "июня",
                "July": "июля", "August": "августа", "September": "сентября",
                "October": "октября", "November": "ноября", "December": "декабря"
            }
            month_ru = next(months_ru[m] for m in months_ru if m in formatted_date)
            day_str = formatted_date.split()[0].lstrip('0')
            formatted_date = f"{day_str} {month_ru}"
        except (ValueError, StopIteration):
            formatted_date = next_user.birthday

        # Создаем список упоминаний всех людей в этот день
        mentions = build_mention_list(users_to_mention)
        
        notification = f"Следующий день рождения:\n{mentions} — {formatted_date}"
        return notification
    
    def get_next_birthday_notification_for_group(self, timezone: ZoneInfo) -> Optional[str]:
        """
        Создает уведомление о следующем дне рождения для беседы.
        Включает всех людей в один и тот же день рождения.
        
        Args:
            timezone: Часовой пояс
            
        Returns:
            Уведомление о ближайшем ДР
        """
        next_user = self.get_next_birthday_user(timezone)
        if not next_user:
            return None
        
        # Находим ВСЕХ пользователей с этим днем рождения
        same_birthday_users = []
        try:
            target_day, target_month = parse_day_month(next_user.birthday)
        except ValueError:
            target_day, target_month = None, None

        for user in self.users:
            try:
                day, month = parse_day_month(user.birthday)
                if day == target_day and month == target_month:
                    same_birthday_users.append(user)
            except ValueError:
                continue
        
        # Если список пустой, используем next_user
        users_to_mention = same_birthday_users if same_birthday_users else [next_user]
        
        # Получаем дату СЛЕДУЮЩЕГО дня рождения
        today = datetime.now(timezone).date()
        try:
            day, month = parse_day_month(next_user.birthday)
            # Ищем следующее наступление этого дня/месяца
            next_year_birthday = date(today.year, month, day)
            if next_year_birthday <= today:
                next_year_birthday = date(today.year + 1, month, day)
            # Форматируем дату: "20 января"
            formatted_date = next_year_birthday.strftime("%d %B").lstrip('0')
            # Переводим месяц на русский
            months_ru = {
                "January": "января", "February": "февраля", "March": "марта",
                "April": "апреля", "May": "мая", "June": "июня",
                "July": "июля", "August": "августа", "September": "сентября",
                "October": "октября", "November": "ноября", "December": "декабря"
            }
            month_ru = next(months_ru[m] for m in months_ru if m in formatted_date)
            day_str = formatted_date.split()[0].lstrip('0')
            formatted_date = f"{day_str} {month_ru}"
        except (ValueError, StopIteration):
            formatted_date = next_user.birthday

        # Создаем список упоминаний всех людей в этот день
        mentions = build_mention_list(users_to_mention)
        
        return f"Следующий день рождения:\n{mentions} — {formatted_date}"
    
    
    def reload_users(self) -> None:
        """
        Перезагружает список пользователей из файла.
        Полезно, если данные были изменены во время работы бота.
        """
        self.users = load_birthdays()

    def save_users(self) -> None:
        """Сохраняет текущий список пользователей в файл."""
        save_birthdays(self.users)


# Создаем глобальный экземпляр сервиса дней рождения
birthday_service = BirthdayService()
