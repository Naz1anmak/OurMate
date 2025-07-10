import json, re
from datetime import datetime
from config import BIRTHDAYS_FILE

def load_birthdays():
    """Загружает список пользователей из файла."""
    with open(BIRTHDAYS_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["users"]

def build_mention_list(users: list[dict]) -> str:
    parts = []
    for u in users:
        name  = u['name']
        login = u['user_login']
        if login:
            parts.append(f"{name} {login}")
        else:
            parts.append(name)
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " и " + parts[-1]

def get_next_birthday(users: list[dict], today_mmdd: str) -> dict | None:
    now = datetime.now()

    def next_dt(u):
        try:
            month, day = map(int, u["birthday"].split("-"))
            dt = datetime(now.year, month, day)
            if dt.strftime("%m-%d") <= today_mmdd:
                dt = dt.replace(year=now.year + 1)
            return dt
        except Exception:
            return datetime.max

    if not users:
        return None
    # min по ключу next_dt(u) вернёт самого «близкого» пользователя
    return min(users, key=next_dt)

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