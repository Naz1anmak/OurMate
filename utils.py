import json
from datetime import datetime
from config import BIRTHDAYS_FILE

def load_birthdays():
    """
    Возвращает кортеж (chat_id, list_of_users),
    где list_of_users — список dict с keys: user_login, name, birthday (MM-DD).
    """
    with open(BIRTHDAYS_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["chat_id"], cfg["users"]

def build_mention_list(users: list[dict]) -> str:
    """
    Строка вида:
    "Имя1 (@login1) и Имя2 (@login2)"
    """
    parts = [
        f"{u['name']} ({u['user_login'] or 'без_ника'})"
        for u in users
    ]
    if len(parts) == 1:
        return parts[0]
    # все кроме последнего, затем "и" + последний
    return ", ".join(parts[:-1]) + " и " + parts[-1]

def today_mmdd(tz) -> str:
    """Возвращает строку 'MM-DD' текущей даты в переданном час. поясе."""
    return datetime.now(tz).strftime("%m-%d")

def get_first_name_by_login(login: str, users: list[dict]) -> str | None:
    """
    Поиск в списке пользователей по полю 'user_login'.
    Если найден — возвращает первое слово из 'name' (Имя). Иначе None.
    """
    if not login:
        return None
    for u in users:
        if u.get("user_login", "").lower() == login.lower():
            # name хранится как "Имя Отчество"
            return u["name"].split()[0]
    return None
