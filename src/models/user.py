"""
Модель пользователя для работы с данными о днях рождения.
Содержит структуру данных и методы для работы с пользователями.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DmState(str, Enum):
    """Доступность пользователя для бота в ЛС (пишется пробером)."""
    UNKNOWN = "unknown"             # ещё не пинговали / старая запись
    REACHABLE = "reachable"         # пинг успешен
    BLOCKED = "blocked"             # 403 «bot was blocked by the user»
    NEVER_STARTED = "never_started" # 403 «bot can't initiate conversation»
    DEACTIVATED = "deactivated"     # 400 «chat not found» / «user is deactivated»


@dataclass
class User:
    """
    Модель пользователя с информацией о дне рождения.

    dm_state — доступность для ЛС (владелец-писатель: пробер расписания).
    subscribed — намерение получать поздравления (владелец: хендлеры «отписаться»/сообщение).
    is_active — производное: подписан И доступен.
    """
    user_id: Optional[int]
    name: str
    last_name: str
    birthday: str
    status: str
    username: Optional[str] = None
    dm_state: DmState = DmState.UNKNOWN
    subscribed: bool = True

    @property
    def is_active(self) -> bool:
        return self.subscribed and self.dm_state == DmState.REACHABLE

    def get_first_name(self) -> str:
        """Возвращает первое слово из полного имени."""
        return self.name.split()[0]

    def mention_html(self) -> str:
        """Создает HTML-упоминание по user_id или возвращает имя.

        Если user_id отсутствует, возвращает имя без ссылки.
        """
        display_name = self.name.lstrip("@")
        display_name = (
            display_name
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        if self.user_id is None:
            return display_name
        return f'<a href="tg://user?id={self.user_id}">{display_name}</a>'

    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        """Создает объект User из словаря (формат dm_state/subscribed)."""
        raw_id = data.get("user_id", "")
        user_id: Optional[int]
        try:
            user_id = int(raw_id) if raw_id is not None and str(raw_id).strip() else None
        except (ValueError, TypeError):
            user_id = None

        username = data.get("username")
        if isinstance(username, str):
            username = username.lstrip("@")
        else:
            username = None

        if "dm_state" in data or "subscribed" in data:
            try:
                dm_state = DmState(data.get("dm_state", DmState.UNKNOWN.value))
            except ValueError:
                dm_state = DmState.UNKNOWN
            subscribed = bool(data.get("subscribed", True))
        else:
            # Минимальная ручная запись {name, birthday} — флаги проставят
            # пробер (dm_state) и взаимодействие пользователя (subscribed).
            dm_state = DmState.UNKNOWN
            subscribed = True

        return cls(
            user_id=user_id,
            name=data["name"],
            last_name=data.get("last_name", ""),
            birthday=data["birthday"],
            status=data.get("status", ""),
            username=username,
            dm_state=dm_state,
            subscribed=subscribed,
        )

    def to_dict(self) -> dict:
        """Преобразует объект User в словарь (новый формат)."""
        data = {
            "user_id": self.user_id,
            "name": self.name,
            "last_name": self.last_name,
            "birthday": self.birthday,
            "status": self.status,
            "dm_state": self.dm_state.value,
            "subscribed": self.subscribed,
        }
        if self.username:
            data["username"] = self.username
        return data
