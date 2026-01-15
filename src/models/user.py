"""
Модель пользователя для работы с данными о днях рождения.
Содержит структуру данных и методы для работы с пользователями.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """
    Модель пользователя с информацией о дне рождения.
    
    Attributes:
        user_id (Optional[int]): Telegram user_id для упоминания по ID
        name (str): Полное имя пользователя
        birthday (str): Дата дня рождения в формате "D.M" или "DD.MM"
        status (str): Статус пользователя (например, "active" или "-")
        interacted_with_bot (bool): Взаимодействовал ли пользователь с ботом
    """
    user_id: Optional[int]
    name: str
    last_name: str
    birthday: str
    status: str
    username: Optional[str] = None
    interacted_with_bot: bool = False
    
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
        """
        Создает объект User из словаря.
        
        Args:
            data (dict): Словарь с данными пользователя
            
        Returns:
            User: Объект пользователя
        """
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

        return cls(
            user_id=user_id,
            name=data["name"],
            last_name=data.get("last_name", ""),
            birthday=data["birthday"],
            status=data.get("status", ""),
            username=username,
            interacted_with_bot=data.get("interacted_with_bot", False),
        )
    
    def to_dict(self) -> dict:
        """
        Преобразует объект User в словарь.
        
        Returns:
            dict: Словарь с данными пользователя
        """
        data = {
            "user_id": self.user_id,
            "name": self.name,
            "last_name": self.last_name,
            "birthday": self.birthday,
            "status": self.status,
            "interacted_with_bot": self.interacted_with_bot,
        }
        if self.username:
            data["username"] = self.username
        return data
