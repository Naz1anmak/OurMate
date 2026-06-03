"""Логика дневного лимита обращений к LLM. Telegram-агностичная сердцевина."""
import logging
from datetime import datetime

from src.config.settings import PM_DAILY_MSG_CAP, CHAT_DAILY_MSG_CAP, TIMEZONE
from src.bot.services.usage_limit_store import usage_limit_store

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


async def enforce_usage_limit(message, tool_context: dict) -> bool:
    """True — обращение заблокировано (блок-сообщение уже отправлено), LLM трогать не нужно."""
    blocked = await check_and_consume(
        usage_limit_store,
        is_owner=bool(tool_context.get("is_owner")),
        is_group=bool(tool_context.get("is_group")),
        chat_id=tool_context["chat_id"],
        user_id=tool_context["user_id"],
        now=datetime.now(TIMEZONE),
        pm_cap=PM_DAILY_MSG_CAP,
        chat_cap=CHAT_DAILY_MSG_CAP,
    )
    if not blocked:
        return False
    # Ленивый импорт — разрывает циклическую зависимость
    # usage_limit → handlers/__init__ → chat_pm → llm_flow → usage_limit
    from src.bot.handlers.usage_limit_variants import pick_limit_variant  # noqa: PLC0415
    text = pick_limit_variant().text
    try:
        if message.chat.type in ("group", "supergroup"):
            await message.reply(text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001 — недоставка блока не критична
        logger.debug("Не удалось отправить блок-сообщение лимита: %s", exc)
    return True
