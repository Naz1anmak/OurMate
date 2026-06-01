"""Обработчик для личных сообщений."""
import logging

from aiogram.types import Message

from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.utils.text_utils import get_first_name_by_user_id
from src.bot.handlers.chat_context import (
    extract_user_login,
    strip_bot_mention,
    build_llm_messages,
)
from src.bot.handlers.llm_flow import run_schedule_aware_response
from src.core.emoji import E
from src.bot.handlers import access

logger = logging.getLogger(__name__)

ERROR_NOTICE_PLAIN_PM = f"{E.WARNING} LLM временно недоступен. Попробуй ещё раз через пару минут."

# Реестр тулов; инжектится из main.py при старте. None → ошибка инициализации (не норма).
tool_registry = None

async def handle_private_chat(message: Message, bot_username: str, bot_id: int, ctx: dict | None = None):
    chat_id = message.chat.id
    text = message.text or ""
    text_for_llm = strip_bot_mention(text, bot_username)

    user_login = extract_user_login(message, text, bot_username)
    user_name = message.from_user.full_name or str(message.from_user.id)
    user_login_safe = user_login or user_name
    if user_login:
        logger.info(f"PM; От {user_login} ({user_name}): {text_for_llm}")
    else:
        logger.info(f"PM; От {user_name}: {text_for_llm}")

    first_name = get_first_name_by_user_id(message.from_user.id, birthday_service.users)
    existing_context = context_service.get_context(chat_id)
    has_context = bool(existing_context)
    messages = build_llm_messages(chat_id, text_for_llm)

    # Единственный путь доставки: тул-флоу (стрим + function calling). В ЛС рефреш/diff отключены by design.
    if tool_registry is None:
        logger.warning("PM; tool_registry не инициализирован — отправляю notice для %s", user_login_safe)
        try:
            await message.answer(ERROR_NOTICE_PLAIN_PM, parse_mode="HTML")
        except Exception:
            pass
        return

    tool_context = {
        "allow_refresh": False,
        "schedule_allowed": bool(ctx and access.resolve(access.Audience.PUBLIC, ctx).allowed),
        "denial_text": access.DENIAL_TEXTS[access.DenialReason.NOT_PRIVILEGED],
        "bot": message.bot,
        "chat_id": message.chat.id,
        "user_id": message.from_user.id,
        "first_name": first_name,
        "is_group": False,
        "is_group_main": False,
        "is_owner": bool(ctx and ctx.get("is_owner")),
    }
    await run_schedule_aware_response(
        message, messages, first_name, user_login, text_for_llm,
        has_context, tool_context, tool_registry)
