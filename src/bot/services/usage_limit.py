"""Логика дневного лимита обращений к LLM. Telegram-агностичная сердцевина."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def check_and_consume(
    store, *, is_owner: bool, is_group: bool, chat_id: int, user_id: int,
    now: datetime, pm_cap: int, chat_cap: int) -> bool:
    """True — лимит исчерпан (блокируем). Владелец всегда пропускается и не считается.

    Счётчик инкрементится ТОЛЬКО когда обращение пропущено — так в usage_counters лежат
    «ответы бота», а не «попытки» (важно для статистики #10). Проверка и инкремент не
    атомарны через await, но процесс один (asyncio): переполнение максимум на 1-2 — ок
    для мягкого лимита.
    """
    if is_owner:
        return False
    scope, key, cap = ("chat", chat_id, chat_cap) if is_group else ("pm_user", user_id, pm_cap)
    day = now.date().isoformat()
    count = await store.get(scope, key, day)
    if count >= cap:
        return True
    await store.increment(scope, key, day)
    return False
