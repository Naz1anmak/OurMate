"""
Сервис для работы с LLM API.
Содержит функции для отправки запросов к языковой модели.
"""
import json
import asyncio
import ssl

import aiohttp
import certifi
import requests
from requests import RequestException
from typing import List, Dict, AsyncGenerator

from src.config.settings import API_URL, API_HEADERS, MODEL

class LLMServiceError(Exception):
    """Ошибка при обращении к LLM API."""

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
        try:
            response = requests.post(
                API_URL,
                headers=API_HEADERS,
                json={"model": MODEL, "messages": messages},
                timeout=45,
            )
        except RequestException as exc:
            raise LLMServiceError(f"HTTP error while calling LLM: {exc}") from exc

        if response.status_code != 200:
            snippet = response.text[:500] if response.text else ""
            raise LLMServiceError(
                f"LLM API returned {response.status_code}. Body: {snippet}"
            )

        try:
            data = response.json()
            full_response = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMServiceError(f"Unexpected LLM response format: {exc}") from exc
        
        # Отделяем мысли от основного ответа
        return LLMService._extract_answer(full_response)

    @staticmethod
    async def stream_chat_request(messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """
        Отправляет стрим-запрос к LLM и возвращает токены по мере генерации.
        Пропускает reasoning-токены, чтобы не выдавать цепочку рассуждений.
        """
        payload = {
            "model": MODEL,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        timeout = aiohttp.ClientTimeout(total=90, sock_read=15)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                async with session.post(API_URL, headers=API_HEADERS, json=payload) as resp:
                    if resp.status != 200:
                        body_snippet = await resp.text()
                        raise LLMServiceError(
                            f"LLM stream returned {resp.status}. Body: {body_snippet[:500]}"
                        )

                    async for raw_chunk in resp.content:
                        if not raw_chunk:
                            continue
                        for raw_line in raw_chunk.splitlines():
                            line = raw_line.decode("utf-8").strip()
                            if not line:
                                continue
                            if line.startswith("data:"):
                                line = line[len("data:"):].strip()
                            if line == "[DONE]":
                                return
                            try:
                                data = json.loads(line)
                            except Exception:
                                continue

                            choices = data.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}

                            # Пропускаем reasoning/details, чтобы не светить мысли
                            token = delta.get("content")
                            if token:
                                yield token

        except aiohttp.ClientError as exc:
            raise LLMServiceError(f"HTTP stream error while calling LLM: {exc}") from exc
        except asyncio.TimeoutError as exc:  # type: ignore[name-defined]
            raise LLMServiceError("LLM stream timed out") from exc
    
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
