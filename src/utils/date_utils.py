"""
Утилиты для работы с датами.
Содержит функции для работы с датами дней рождения и планировщиком.
"""

from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from src.models.user import User


def today_mmdd(timezone: ZoneInfo) -> str:
    """
    Возвращает текущую дату в формате 'MM-DD' в указанном часовом поясе.
    
    Args:
        timezone (ZoneInfo): Часовой пояс
        
    Returns:
        str: Дата в формате 'MM-DD'
    """
    return datetime.now(timezone).strftime("%m-%d")


def get_next_birthday(users: List[User], today_mmdd: str) -> Optional[User]:
    """
    Находит пользователя с ближайшим днем рождения.
    
    Args:
        users (List[User]): Список пользователей
        today_mmdd (str): Текущая дата в формате 'MM-DD'
        
    Returns:
        Optional[User]: Пользователь с ближайшим днем рождения или None
    """
    now = datetime.now()
    
    def next_dt(user: User) -> datetime:
        """
        Вычисляет дату следующего дня рождения для пользователя.
        
        Args:
            user (User): Пользователь
            
        Returns:
            datetime: Дата следующего дня рождения
        """
        try:
            month, day = map(int, user.birthday.split("-"))
            dt = datetime(now.year, month, day)
            
            # Если день рождения уже прошел в этом году, 
            # считаем что он будет в следующем году
            if dt.strftime("%m-%d") <= today_mmdd:
                dt = dt.replace(year=now.year + 1)
            return dt
        except Exception:
            # В случае ошибки возвращаем максимальную дату
            return datetime.max
    
    if not users:
        return None
    
    # Находим пользователя с минимальной датой следующего дня рождения
    return min(users, key=next_dt)


def format_birthday_date(birthday: str) -> str:
    """
    Форматирует дату дня рождения в читаемый вид.
    
    Args:
        birthday (str): Дата в формате 'MM-DD'
        
    Returns:
        str: Отформатированная дата (например, "15 января")
    """
    # Словарь названий месяцев на русском языке
    month_names = {
        1: "января", 2: "февраля", 3: "марта",
        4: "апреля", 5: "мая", 6: "июня",
        7: "июля", 8: "августа", 9: "сентября",
        10: "октября", 11: "ноября", 12: "декабря"
    }
    
    month, day = map(int, birthday.split("-"))
    return f"{day} {month_names[month]}"
