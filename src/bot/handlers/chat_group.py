"""Обработчик для групповых сообщений."""
import logging
import time

from aiogram.types import Message

from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.utils.text_utils import get_first_name_by_user_id
from src.bot.handlers.chat_context import (
    extract_user_login,
    strip_bot_mention,
    build_group_llm_input,
    build_llm_messages,
)
from src.bot.handlers.llm_flow import run_schedule_aware_response, ERROR_NOTICE_PLAIN
from src.bot.handlers import access

logger = logging.getLogger(__name__)

# Реестр тулов; инжектится из main.py при старте. None → ошибка инициализации (не норма).
tool_registry = None

_PROCESSED_GROUP_MESSAGES: dict[tuple[int, int], float] = {}
_PROCESSED_GROUP_TTL_SECONDS = 300.0
_LAST_GROUP_DEDUP_CLEANUP_TS = 0.0

def _cleanup_processed_group_messages(now_ts: float) -> None:
    global _LAST_GROUP_DEDUP_CLEANUP_TS
    if now_ts - _LAST_GROUP_DEDUP_CLEANUP_TS < 60:
        return
    _LAST_GROUP_DEDUP_CLEANUP_TS = now_ts
    stale_keys = [
        key
        for key, ts in _PROCESSED_GROUP_MESSAGES.items()
        if (now_ts - ts) > _PROCESSED_GROUP_TTL_SECONDS
    ]
    for key in stale_keys:
        _PROCESSED_GROUP_MESSAGES.pop(key, None)


async def handle_group_chat(message: Message, bot_username: str, bot_id: int, ctx: dict | None = None):
    chat_id = message.chat.id
    text = message.text or ""
    text_for_llm = strip_bot_mention(text, bot_username)

    # Триггер-гейт групп выполнен выше в chat.py (detect_trigger) — повторно не проверяем.

    # Дедупликация на случай повторной доставки одного и того же апдейта при сетевых сбоях polling.
    message_key = (chat_id, message.message_id)
    now_ts = time.monotonic()
    _cleanup_processed_group_messages(now_ts)
    prev_ts = _PROCESSED_GROUP_MESSAGES.get(message_key)
    if prev_ts is not None and (now_ts - prev_ts) <= _PROCESSED_GROUP_TTL_SECONDS:
        logger.warning(f"GR; Duplicate message skipped: chat_id={chat_id}, message_id={message.message_id}")
        return
    _PROCESSED_GROUP_MESSAGES[message_key] = now_ts

    user_login = extract_user_login(message, text, bot_username)
    user_name = message.from_user.full_name or str(message.from_user.id)
    user_login_safe = user_login or user_name
    reply_context_used = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id != bot_id
        and ((message.reply_to_message.text or message.reply_to_message.caption) or "").strip()
    )
    reply_context_from = ""
    if reply_context_used and message.reply_to_message and message.reply_to_message.from_user:
        reply_from_user = message.reply_to_message.from_user
        reply_context_from = (
            f"@{reply_from_user.username}"
            if reply_from_user.username
            else (reply_from_user.full_name or str(reply_from_user.id))
        )
    reply_context_note = f" + reply-context from {reply_context_from}" if reply_context_from else (" + reply-context" if reply_context_used else "")
    if user_login:
        logger.info(f"GR; От {user_login} ({user_name}){reply_context_note}: {text_for_llm}")
    else:
        logger.info(f"GR; От {user_name}{reply_context_note}: {text_for_llm}")

    first_name = get_first_name_by_user_id(message.from_user.id, birthday_service.users)
    existing_context = context_service.get_context(chat_id)
    has_context = bool(existing_context)
    llm_input_text = build_group_llm_input(message, text_for_llm, bot_id)
    messages = build_llm_messages(chat_id, llm_input_text)

    # Единственный путь доставки: тул-флоу (стрим + function calling). В группе рефреш/diff включены.
    if tool_registry is None:
        logger.warning("GR; tool_registry не инициализирован — отправляю notice для %s", user_login_safe)
        try:
            await message.reply(ERROR_NOTICE_PLAIN, parse_mode="HTML")
        except Exception:
            pass
        return

    reply_user = None
    if (message.reply_to_message and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id != bot_id):
        ru = message.reply_to_message.from_user
        reply_user = {"user_id": ru.id, "username": ru.username}
    mentioned_users = []
    for ent in (message.entities or []):
        if ent.type == "text_mention" and ent.user:
            mentioned_users.append({"user_id": ent.user.id, "username": ent.user.username})

    tool_context = {
        "allow_refresh": True,
        "schedule_allowed": bool(ctx and access.resolve(access.Audience.PUBLIC, ctx).allowed),
        "denial_text": access.DENIAL_TEXTS[access.DenialReason.FOREIGN_GROUP],
        "bot": message.bot,
        "chat_id": message.chat.id,
        "user_id": message.from_user.id,
        "first_name": first_name,
        "username": message.from_user.username,
        "is_group": True,
        "is_group_main": bool(ctx and ctx.get("is_group_main")),
        "is_owner": bool(ctx and ctx.get("is_owner")),
        "reply_user": reply_user,
        "mentioned_users": mentioned_users,
    }
    await run_schedule_aware_response(
        message, messages, first_name, user_login, text_for_llm,
        has_context, tool_context, tool_registry)
