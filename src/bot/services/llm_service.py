"""
Сервис для работы с LLM API.
Содержит функции для отправки запросов к языковой модели.
"""
import requests
from typing import List, Dict, Any

from src.config.settings import API_URL, API_HEADERS, MODEL

class LLMService:
    """
    Сервис для работы с внешним LLM API.
    Обрабатывает запросы к языковой модели и форматирует ответы.
    """
    
    @staticmethod
    def send_chat_request(messages: List[Dict[str, str]]) -> str:
        """
        Отправляет запрос к LLM для генерации ответа в чате.
        
        Args:
            messages (List[Dict[str, str]]): Список сообщений в формате OpenAI API
            
        Returns:
            str: Сгенерированный ответ от LLM
        """
        response = requests.post(API_URL, headers=API_HEADERS, json={
            "model": MODEL,
            "messages": messages
        })
        
        data = response.json()
        full_response = data["choices"][0]["message"]["content"]
        
        # Отделяем мысли от основного ответа
        return LLMService._extract_answer(full_response)
    
    @staticmethod
    def send_birthday_request(prompt: str) -> str:
        """
        Отправляет запрос к LLM для генерации поздравления.
        
        Args:
            prompt (str): Промпт для генерации поздравления
            
        Returns:
            str: Сгенерированное поздравление
        """
        messages = [
            {"role": "system", "content": "Ты — бот-поздравлятор для студентов."},
            {"role": "user", "content": prompt}
        ]
        
        response = requests.post(API_URL, headers=API_HEADERS, json={
            "model": MODEL,
            "messages": messages
        })
        
        data = response.json()
        full_response = data["choices"][0]["message"]["content"]
        
        # Отделяем мысли от основного ответа
        return LLMService._extract_answer(full_response)
    
    @staticmethod
    def _extract_answer(full_response: str) -> str:
        """
        Извлекает основной ответ из полного ответа LLM.
        Удаляет секцию "мысли" если она присутствует.
        
        Args:
            full_response (str): Полный ответ от LLM
            
        Returns:
            str: Очищенный ответ
        """
        if "</think>\n" in full_response:
            # Если есть секция мыслей, берем только основную часть
            return full_response.split("</think>\n")[-1].strip()
        else:
            # Если секции мыслей нет, возвращаем весь ответ
            return full_response.strip()
