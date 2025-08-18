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
        user_login (str): Логин пользователя в Telegram (например, "@username")
        name (str): Полное имя пользователя
        birthday (str): Дата дня рождения в формате "MM-DD"
    """
    user_login: str
    name: str
    birthday: str
    
    def get_first_name(self) -> str:
        """
        Возвращает первое имя пользователя.
        
        Returns:
            str: Первое слово из полного имени
        """
        return self.name.split()[0]
    
    def get_mention_text(self) -> str:
        """
        Возвращает текст для упоминания пользователя.
        
        Returns:
            str: Имя с логином или только имя, если логин отсутствует
        """
        if self.user_login:
            return f"{self.name} {self.user_login}"
        return self.name
    
    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        """
        Создает объект User из словаря.
        
        Args:
            data (dict): Словарь с данными пользователя
            
        Returns:
            User: Объект пользователя
        """
        return cls(
            user_login=data.get('user_login', ''),
            name=data['name'],
            birthday=data['birthday']
        )
    
    def to_dict(self) -> dict:
        """
        Преобразует объект User в словарь.
        
        Returns:
            dict: Словарь с данными пользователя
        """
        return {
            'user_login': self.user_login,
            'name': self.name,
            'birthday': self.birthday
        }
