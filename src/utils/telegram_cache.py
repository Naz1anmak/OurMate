"""
Кеширование информации о боте (bot.get_me) для снижения сетевых вызовов.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple, Any

_BOT_INFO_CACHE: dict[str, Any] = {"info": None, "username": None}
_BOT_INFO_LOCK = asyncio.Lock()

async def get_cached_bot_identity(bot) -> Tuple[Any, Optional[str]]:
    """Возвращает (bot_info, bot_username) с кешированием bot.get_me()."""
    cached = _BOT_INFO_CACHE.get("info")
    if cached is not None:
        return cached, _BOT_INFO_CACHE.get("username")

    async with _BOT_INFO_LOCK:
        cached = _BOT_INFO_CACHE.get("info")
        if cached is not None:
            return cached, _BOT_INFO_CACHE.get("username")
        info = await bot.get_me()
        username = f"@{info.username}" if getattr(info, "username", None) else None
        _BOT_INFO_CACHE["info"] = info
        _BOT_INFO_CACHE["username"] = username
        return info, username

def get_cached_bot_info() -> Any | None:
    """Возвращает закэшированный bot_info или None."""
    return _BOT_INFO_CACHE.get("info")

def get_cached_bot_username() -> Optional[str]:
    """Возвращает закэшированный username вида @name или None."""
    return _BOT_INFO_CACHE.get("username")
