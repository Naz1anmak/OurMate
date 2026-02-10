"""
Утилиты для работы с датами.
Содержит функции для работы с датами дней рождения и планировщиком.
"""
from datetime import datetime, date
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.models.user import User

MONTH_NAMES_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

def _parse_day_month(birthday: str) -> Tuple[int, int]:
    """Парсит дату формата 'D.M' или 'DD.MM' в кортеж (day, month)."""
    if "." not in birthday:
        raise ValueError(f"Invalid birthday format: {birthday}")
    parts = birthday.split(".")
    if len(parts) != 2:
        raise ValueError(f"Invalid birthday format: {birthday}")
    day_part, month_part = parts
    day = int(day_part)
    month = int(month_part)
    return day, month

def parse_day_month(birthday: str) -> Tuple[int, int]:
    """Публичная обертка для разбора даты рождения."""
    return _parse_day_month(birthday)

def today_mmdd(timezone: ZoneInfo) -> str:
    """Возвращает текущую дату в формате 'D.M' (без ведущих нулей)."""
    now = datetime.now(timezone)
    return f"{now.day}.{now.month}"

def get_next_birthday(users: List[User], today_dm: str) -> Optional[User]:
    """
    Находит пользователя с ближайшим днем рождения.
    
    Args:
        users (List[User]): Список пользователей
        today_mmdd (str): Текущая дата в формате 'MM-DD'
        
    Returns:
        Optional[User]: Пользователь с ближайшим днем рождения или None
    """
    now = datetime.now()
    try:
        today_day, today_month = _parse_day_month(today_dm)
    except ValueError:
        return None
    
    def next_dt(user: User) -> datetime:
        """
        Вычисляет дату следующего дня рождения для пользователя.
        
        Args:
            user (User): Пользователь
            
        Returns:
            datetime: Дата следующего дня рождения
        """
        try:
            day, month = _parse_day_month(user.birthday)
            dt = datetime(now.year, month, day)
            
            # Если день рождения уже прошел или сегодня,
            # считаем что он будет в следующем году
            if (month, day) <= (today_month, today_day):
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
    day, month = _parse_day_month(birthday)
    return f"{day} {MONTH_NAMES_RU[month]}"

def format_next_birthday_date(birthday: str, timezone: ZoneInfo) -> str:
    """
    Возвращает ближайшую будущую дату дня рождения в формате "20 января".

    Args:
        birthday (str): Дата в формате "D.M" или "DD.MM"
        timezone (ZoneInfo): Часовой пояс

    Returns:
        str: Отформатированная дата или исходная строка при ошибке
    """
    try:
        day, month = _parse_day_month(birthday)
        today = datetime.now(timezone).date()
        next_bday = date(today.year, month, day)
        if next_bday <= today:
            next_bday = date(today.year + 1, month, day)
        return f"{next_bday.day} {MONTH_NAMES_RU[next_bday.month]}"
    except Exception:
        return birthday
