"""
Утилиты для работы с текстом.
Содержит функции для форматирования текста и работы с пользователями.
"""
import json
from typing import List, Optional

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

def save_birthdays(users: List[User]) -> None:
    """Сохраняет список пользователей в JSON файл."""
    payload = {"users": [user.to_dict() for user in users]}
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

def build_mention_list(users: List[User]) -> str:
    """Создает HTML-список упоминаний пользователей с логином, если он есть."""
    if not users:
        return ""

    def _fmt(user: User) -> str:
        username_info = f" (@{user.username})" if user.username else ""
        return f"{user.mention_html()}{username_info}"

    mention_texts = [_fmt(user) for user in users]

    if len(mention_texts) == 1:
        return mention_texts[0]

    return ", ".join(mention_texts[:-1]) + " и " + mention_texts[-1]

def get_first_name_by_user_id(user_id: int, users: List[User]) -> Optional[str]:
    """Ищет имя по user_id в списке пользователей."""
    for user in users:
        if user.user_id == user_id:
            return user.get_first_name()
    return None


def get_user_id_by_username(username: str, users: List[User]) -> Optional[int]:
    """user_id по @username из ростера (регистронезависимо, ведущий @ игнорируется)."""
    key = (username or "").lstrip("@").lower()
    if not key:
        return None
    for u in users:
        if u.username and u.username.lstrip("@").lower() == key:
            return u.user_id
    return None


def find_users_by_fullname(query: str, users: List[User]) -> List[User]:
    """Кандидаты по ФИО: все слова запроса встречаются в 'last_name name' (регистронезависимо)."""
    tokens = [t for t in (query or "").lower().split() if t]
    if not tokens:
        return []
    out: List[User] = []
    for u in users:
        haystack = f"{u.last_name} {u.name}".lower()
        if all(tok in haystack for tok in tokens):
            out.append(u)
    return out


def roster_full_name(user: User) -> str:
    """«Фамилия Имя» для официального рендера. Если last_name пуст или уже входит в name — только name."""
    name = (user.name or "").strip()
    last = (user.last_name or "").strip()
    if last and last.lower() not in name.lower():
        return f"{last} {name}".strip()
    return name
