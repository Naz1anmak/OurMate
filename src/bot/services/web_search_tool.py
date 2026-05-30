"""Тул веб-поиска через Tavily Search API для tool use."""
import logging
import ssl
from datetime import datetime
from typing import Awaitable, Callable, Optional

import aiohttp
import certifi

from src.bot.services.llm_tools import ToolRegistry, ToolSpec
from src.config.settings import (
    TAVILY_API_KEY, TAVILY_MAX_RESULTS, TAVILY_SEARCH_DEPTH, TAVILY_URL,
    TIMEZONE, WEB_SEARCH_DAILY_CAP,
)

logger = logging.getLogger(__name__)

# Дневной счётчик запросов (in-memory, без БД): сбрасывается при смене даты.
_usage = {"date": None, "count": 0}


async def _tavily_request(query: str, *, api_key: str = TAVILY_API_KEY,
                          max_results: int = TAVILY_MAX_RESULTS,
                          search_depth: str = TAVILY_SEARCH_DEPTH,
                          url: str = TAVILY_URL) -> dict:
    """Реальный HTTP-вызов Tavily. Возвращает распарсенный JSON или кидает исключение."""
    payload = {
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": True,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=20, sock_read=10)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(timeout=timeout,
                                     connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Tavily {resp.status}: {body[:300]}")
            return await resp.json()


def _trim_results(raw: list) -> list[dict]:
    """Оставляет только title/url/content из результатов Tavily."""
    out = []
    for r in raw or []:
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        })
    return out


async def web_search(
    query: str,
    *,
    tool_context: dict,
    search_fn: Callable[..., Awaitable[dict]] = _tavily_request,
    now: Optional[datetime] = None,
    daily_cap: int = WEB_SEARCH_DAILY_CAP,
) -> dict:
    """Ищет в интернете через Tavily. Возвращает {answer, results, error}."""
    if not query or not query.strip():
        return {"answer": None, "results": [], "error": "search_failed"}

    today = (now or datetime.now(TIMEZONE)).date()
    if _usage["date"] != today:
        _usage["date"] = today
        _usage["count"] = 0
    if _usage["count"] >= daily_cap:
        logger.info("web_search: дневной кап %s исчерпан", daily_cap)
        return {"answer": None, "results": [], "error": "quota_exhausted"}
    _usage["count"] += 1

    try:
        data = await search_fn(query)
    except Exception as exc:  # noqa: BLE001 — не падаем, отдаём структурную ошибку
        logger.warning("web_search упал: %s", exc)
        return {"answer": None, "results": [], "error": "search_failed"}

    return {
        "answer": data.get("answer"),
        "results": _trim_results(data.get("results")),
        "error": None,
    }


WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Поиск в интернете для свежих/проверяемых фактов, которых нет в расписании, "
            "памяти или знаниях модели: новости, «что вышло», курсы, погода, события. "
            "Вызывай, когда для ответа нужны актуальные данные, ИЛИ когда пользователь "
            "прямо просит «загугли …», «найди в интернете …», «поищи …». "
            "Возвращает answer (сжатый ответ) и results (источники с url)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос на естественном языке."},
            },
            "required": ["query"],
        },
    },
}


def build_web_search_registry() -> ToolRegistry:
    """Реестр с единственным тулом web_search (без гейта — доступен всем)."""
    reg = ToolRegistry()
    reg.register("web_search", ToolSpec(schema=WEB_SEARCH_SCHEMA, func=web_search, gate=None))
    return reg
