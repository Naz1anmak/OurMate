"""
Сервис для управления контекстом диалогов.
Хранит историю сообщений для каждого чата.
"""
import time
from typing import Dict, List, Optional, Tuple

class ContextService:
    """
    Сервис для управления контекстом диалогов с пользователями.
    Хранит последние пары вопрос–ответ для каждого чата с ограничением по времени.
    """
    
    def __init__(self, ttl_seconds: int = 24 * 60 * 60, max_pairs: int = 2):
        # Словарь для хранения контекста: chat_id -> список пар (вопрос, ответ, timestamp)
        self._context_store: Dict[int, List[Tuple[str, str, float]]] = {}
        self._ttl_seconds = ttl_seconds
        self._max_pairs = max_pairs
    
    def get_context(self, chat_id: int) -> Optional[List[Tuple[str, str]]]:
        """
        Получает контекст для указанного чата в пределах TTL.
        
        Args:
            chat_id (int): ID чата
            
        Returns:
            Optional[List[Tuple[str, str]]]: Список пар (вопрос, ответ) или None, если контекста нет
        """
        fresh_pairs = self._prune_and_get(chat_id)
        if not fresh_pairs:
            return None
        return [(q, a) for q, a, _ in fresh_pairs]
    
    def save_context(self, chat_id: int, question: str, answer: str) -> None:
        """
        Сохраняет контекст для указанного чата.
        Сохраняет до `max_pairs` последних пар внутри окна TTL.
        
        Args:
            chat_id (int): ID чата
            question (str): Вопрос пользователя
            answer (str): Ответ бота
        """
        now = time.time()
        current_pairs = self._prune_and_get(chat_id)
        current_pairs.append((question, answer, now))
        self._context_store[chat_id] = current_pairs[-self._max_pairs :]
    
    def clear_context(self, chat_id: int) -> None:
        """
        Очищает контекст для указанного чата.
        
        Args:
            chat_id (int): ID чата
        """
        if chat_id in self._context_store:
            del self._context_store[chat_id]
    
    def get_all_contexts(self) -> Dict[int, List[Tuple[str, str]]]:
        """
        Возвращает все сохраненные контексты.
        
        Returns:
            Dict[int, List[Tuple[str, str]]]: Словарь всех контекстов
        """
        result: Dict[int, List[Tuple[str, str]]] = {}
        for chat_id in list(self._context_store.keys()):
            pairs = self.get_context(chat_id)
            if pairs:
                result[chat_id] = pairs
        return result
    
    def clear_all_contexts(self) -> None:
        """
        Очищает все сохраненные контексты.
        """
        self._context_store.clear()

    def _prune_and_get(self, chat_id: int) -> List[Tuple[str, str, float]]:
        """Удаляет устаревшие пары и возвращает свежие для чата."""
        now = time.time()
        pairs = self._context_store.get(chat_id, [])
        fresh = [item for item in pairs if now - item[2] <= self._ttl_seconds]
        self._context_store[chat_id] = fresh
        return fresh

# Создаем глобальный экземпляр сервиса контекста
context_service = ContextService()
