"""Вспомогательные функции для построения контекста и подготовки сообщений LLM."""
from aiogram.types import Message

from src.config.settings import PROMPT_TEMPLATE_CHAT, OWNER_CHAT_ID, CHAT_ID
from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service

def is_public_command(text: str) -> bool:
    """Возвращает True для публичных команд др/пары."""
    return (
        text == "др"
        or text.startswith("др ")
        or text == "пары"
        or text == "пары завтра"
    )

def build_command_context(message: Message, bot_username: str, bot_id: int) -> dict:
    text = message.text or ""
    is_mention = any(token == bot_username for token in text.split())
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_id

    text_for_commands = text
    if is_mention:
        text_for_commands = " ".join([token for token in text.split() if token != bot_username])

    normalized_text = text_for_commands.lower().strip()

    is_owner = message.from_user and message.from_user.id == OWNER_CHAT_ID
    is_group_chat = message.chat.type in ("group", "supergroup")
    is_group_main = is_group_chat and message.chat.id == CHAT_ID
    is_owner_pm = message.chat.type == "private" and is_owner
    is_private_non_owner = message.chat.type == "private" and not is_owner
    is_whitelisted_private = is_private_non_owner and any(
        user.user_id == message.from_user.id for user in birthday_service.users if user.user_id is not None
    )

    is_main_trigger = is_group_main and (is_mention or is_reply)
    is_owner_trigger = is_owner and is_group_chat and (is_mention or is_reply)

    should_process_birthday_command = is_owner_pm or is_main_trigger or is_owner_trigger or is_whitelisted_private
    should_process_schedule_command = is_owner_pm or is_main_trigger or is_owner_trigger or is_whitelisted_private

    return {
        "text_for_commands": text_for_commands,
        "normalized_text": normalized_text,
        "is_mention": is_mention,
        "is_reply": is_reply,
        "is_owner": is_owner,
        "is_group_chat": is_group_chat,
        "is_group_main": is_group_main,
        "is_owner_pm": is_owner_pm,
        "is_private_non_owner": is_private_non_owner,
        "is_whitelisted_private": is_whitelisted_private,
        "is_main_trigger": is_main_trigger,
        "is_owner_trigger": is_owner_trigger,
        "should_process_birthday_command": should_process_birthday_command,
        "should_process_schedule_command": should_process_schedule_command,
    }

def should_process_message(message: Message, bot_username: str, bot_id: int) -> bool:
    """
    Проверяет, нужно ли обрабатывать сообщение.
    """
    # В личных сообщениях обрабатываем все
    if message.chat.type not in ("group", "supergroup"):
        return True

    # В группе обрабатываем только упоминания или ответы на сообщения бота
    is_mention = any(token == bot_username for token in (message.text or "").split())
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_id

    return is_mention or is_reply

def extract_user_login(message: Message, text: str, bot_username: str) -> str:
    """Извлекает логин пользователя из сообщения."""
    if message.from_user and message.from_user.username:
        return "@" + message.from_user.username

    if any(token == bot_username for token in text.split()):
        for token in text.split():
            if token.startswith("@") and token != bot_username:
                return token

    return ""

def strip_bot_mention(text: str, bot_username: str) -> str:
    """Убирает прямое упоминание бота, чтобы не попадало в LLM."""
    if not text:
        return text
    tokens = text.split()
    filtered = [t for t in tokens if t != bot_username]
    if len(filtered) != len(tokens):
        return " ".join(filtered).strip(" ,")
    if text.startswith(bot_username):
        return text[len(bot_username):].strip(" ,")
    return text

def build_group_llm_input(
    message: Message,
    current_text: str,
    bot_id: int,
    max_reply_len: int = 1200,
) -> str:
    """Собирает вход в LLM для групп: добавляет контекст реплая только на чужие сообщения."""
    base_text = (current_text or "").strip()
    reply = message.reply_to_message
    if not reply:
        return base_text

    # Если это reply на сообщение самого бота, дополнительный reply-context не нужен.
    if reply.from_user and reply.from_user.id == bot_id:
        return base_text

    reply_text = ((reply.text or reply.caption) or "").strip()
    if not reply_text:
        return base_text

    if len(reply_text) > max_reply_len:
        reply_text = reply_text[:max_reply_len].rstrip() + "…"

    reply_author = None
    if reply.from_user:
        reply_author = reply.from_user.full_name or (f"@{reply.from_user.username}" if reply.from_user.username else None)
    reply_author = reply_author or "пользователь"

    if base_text:
        return (
            f"Контекст реплая от {reply_author}:\n"
            f"{reply_text}\n\n"
            f"Текущее сообщение: {base_text}"
        )

    return (
        f"Контекст реплая от {reply_author}:\n"
        f"{reply_text}\n\n"
        "Пользователь обратился к тебе в реплае без дополнительного текста."
    )

def build_llm_messages(chat_id: int, current_text: str, user_id: int | None = None) -> list:
    """Формирует список сообщений для отправки в LLM."""
    messages = [{"role": "system", "content": PROMPT_TEMPLATE_CHAT}]

    prev_pairs = context_service.get_context(chat_id)
    if prev_pairs:
        for question, answer in prev_pairs:
            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": answer})

    messages.append({"role": "user", "content": current_text})
    return messages
