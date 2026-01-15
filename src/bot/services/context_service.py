"""
Сервис для управления контекстом диалогов.
Хранит историю сообщений для каждого чата.
"""
from typing import Dict, List, Optional

class ContextService:
    """
    Сервис для управления контекстом диалогов с пользователями.
    Хранит последний вопрос и ответ для каждого чата.
    """
    
    def __init__(self):
        # Словарь для хранения контекста: chat_id -> [вопрос, ответ]
        self._context_store: Dict[int, List[str]] = {}
    
    def get_context(self, chat_id: int) -> Optional[List[str]]:
        """
        Получает контекст для указанного чата.
        
        Args:
            chat_id (int): ID чата
            
        Returns:
            Optional[List[str]]: Список [вопрос, ответ] или None, если контекста нет
        """
        return self._context_store.get(chat_id)
    
    def save_context(self, chat_id: int, question: str, answer: str) -> None:
        """
        Сохраняет контекст для указанного чата.
        
        Args:
            chat_id (int): ID чата
            question (str): Вопрос пользователя
            answer (str): Ответ бота
        """
        self._context_store[chat_id] = [question, answer]
    
    def clear_context(self, chat_id: int) -> None:
        """
        Очищает контекст для указанного чата.
        
        Args:
            chat_id (int): ID чата
        """
        if chat_id in self._context_store:
            del self._context_store[chat_id]
    
    def get_all_contexts(self) -> Dict[int, List[str]]:
        """
        Возвращает все сохраненные контексты.
        
        Returns:
            Dict[int, List[str]]: Словарь всех контекстов
        """
        return self._context_store.copy()
    
    def clear_all_contexts(self) -> None:
        """
        Очищает все сохраненные контексты.
        """
        self._context_store.clear()

# Создаем глобальный экземпляр сервиса контекста
context_service = ContextService()
