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
from typing import Awaitable, Callable, List, Dict, AsyncGenerator, Optional

from src.config.settings import API_URL, API_HEADERS, MODEL
from src.bot.services.llm_tools import LLMReply

class LLMServiceError(Exception):
    """Ошибка при обращении к LLM API."""


def accumulate_tool_calls(acc: dict, deltas: list) -> None:
    """Склеивает фрагменты tool_calls по index из стрим-дельт OpenAI-формата."""
    for d in deltas or []:
        idx = d.get("index", 0)
        slot = acc.setdefault(idx, {"id": None, "type": "function",
                                    "function": {"name": "", "arguments": ""}})
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]


async def stream_with_tools(
    messages: list,
    tools: Optional[list],
    on_content_token: Optional[Callable[[str], Awaitable[None]]] = None,
) -> LLMReply:
    """Один стрим-вызов с тулами. content-токены отдаёт в on_content_token; копит reasoning и tool_calls."""
    payload = {"model": MODEL, "messages": messages, "stream": True,
               "stream_options": {"include_usage": True}}
    if tools:
        payload["tools"] = tools

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_acc: dict = {}

    timeout = aiohttp.ClientTimeout(total=120, sock_read=15)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post(API_URL, headers=API_HEADERS, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise LLMServiceError(f"LLM tools stream returned {resp.status}. Body: {body[:500]}")
                async for raw_chunk in resp.content:
                    for raw_line in raw_chunk.splitlines():
                        line = raw_line.decode("utf-8").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        line = line[len("data:"):].strip()
                        if line == "[DONE]":
                            break
                        try:
                            data = json.loads(line)
                        except Exception:
                            continue
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        if delta.get("reasoning_content"):
                            reasoning_parts.append(delta["reasoning_content"])
                        if delta.get("tool_calls"):
                            accumulate_tool_calls(tool_acc, delta["tool_calls"])
                        token = delta.get("content")
                        if token:
                            content_parts.append(token)
                            if on_content_token:
                                await on_content_token(token)
    except aiohttp.ClientError as exc:
        raise LLMServiceError(f"HTTP tools stream error: {exc}") from exc
    except asyncio.TimeoutError as exc:
        raise LLMServiceError("LLM tools stream timed out") from exc

    tool_calls = [tool_acc[i] for i in sorted(tool_acc)] or None
    return LLMReply(
        content="".join(content_parts) or None,
        tool_calls=tool_calls,
        reasoning_content="".join(reasoning_parts) or None,
    )

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
                timeout=30,
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

        # Таймауты стрима: до 60с на весь ответ и до 8с между чанками
        timeout = aiohttp.ClientTimeout(total=60, sock_read=8)
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
