"""
Утилиты для работы с текстом.
Содержит функции для форматирования текста и работы с пользователями.
"""

import json
from typing import List, Optional
from pathlib import Path

from src.models.user import User
from src.config.settings import BIRTHDAYS_FILE


def load_birthdays() -> List[User]:
    """
    Загружает список пользователей из JSON файла.
    
    Returns:
        List[User]: Список пользователей с днями рождения
    """
    with open(BIRTHDAYS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    
    # Преобразуем словари в объекты User
    return [User.from_dict(user_data) for user_data in data["users"]]


def build_mention_list(users: List[User]) -> str:
    """
    Создает список упоминаний пользователей для отображения.
    
    Args:
        users (List[User]): Список пользователей
        
    Returns:
        str: Отформатированный список упоминаний
    """
    if not users:
        return ""
    
    # Получаем тексты упоминаний для каждого пользователя
    mention_texts = [user.get_mention_text() for user in users]
    
    if len(mention_texts) == 1:
        return mention_texts[0]
    
    # Для нескольких пользователей используем "и" перед последним
    return ", ".join(mention_texts[:-1]) + " и " + mention_texts[-1]


def get_first_name_by_login(login: str, users: List[User]) -> Optional[str]:
    """
    Находит пользователя по логину и возвращает его первое имя.
    
    Args:
        login (str): Логин пользователя (например, "@username")
        users (List[User]): Список пользователей для поиска
        
    Returns:
        Optional[str]: Первое имя пользователя или None, если не найден
    """
    if not login:
        return None
    
    # Ищем пользователя с совпадающим логином (без учета регистра)
    for user in users:
        if user.user_login.lower() == login.lower():
            return user.get_first_name()
    
    return None
