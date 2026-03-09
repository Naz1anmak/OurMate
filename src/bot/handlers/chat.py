"""
Обработчики чата.
Содержит функции для обработки обычных сообщений и упоминаний бота.
"""
from aiogram.types import Message

from src.config.settings import OWNER_CHAT_ID
from src.bot.services.birthday_service import birthday_service
from src.bot.handlers.chat_context import build_command_context, is_public_command
from src.bot.handlers.chat_commands import (
    handle_help_command,
    handle_unsubscribe_command,
    handle_owner_commands,
    handle_public_commands,
)
from src.bot.handlers.chat_pm import handle_private_chat
from src.bot.handlers.chat_group import handle_group_chat
from src.utils.log_utils import log_with_ts as _log
from src.utils.emoji_utils import make_custom_emoji_payload

EMOJI_ID_CROSS = "5465665476971471368"
from src.utils.telegram_cache import (
    get_cached_bot_identity,
    get_cached_bot_info,
    get_cached_bot_username,
)

async def on_mention_or_reply(message: Message):
    """
    Обработчик для упоминаний бота и ответов на его сообщения.
    Обрабатывает сообщения в группах и личных чатах.
    
    Args:
        message (Message): Входящее сообщение
    """
    # Предварительно нормализуем текст (для ЛС-активации)
    normalized_text = message.text.lower().strip() if message.text else ""

    # Отслеживаем взаимодействие с ботом в ЛС, кроме явной команды "отписаться"
    if message.chat.type == "private" and message.from_user:
        user = next((u for u in birthday_service.users if u.user_id == message.from_user.id), None)
        if user and not user.interacted_with_bot and normalized_text != "отписаться":
            user.interacted_with_bot = True
            birthday_service.save_users()
    
    # Инициализируем переменные бота в начале функции
    bot = message.bot
    try:
        bot_info, cached_username = await get_cached_bot_identity(bot)
    except Exception as exc:
        cached_info = get_cached_bot_info()
        if cached_info is None:
            _log(f"[SYSTEM] bot.get_me() недоступен: {exc}")
            return
        bot_info = cached_info
        cached_username = get_cached_bot_username()
    bot_username = cached_username or f"@{bot_info.username}"
    ctx = build_command_context(message, bot_username, bot_info.id) if message.text else None

    # Команды: help/команды доступны всем; остальные — только владельцу
    if ctx:
        if await handle_help_command(message, ctx["normalized_text"]):
            return

        if await handle_unsubscribe_command(message, ctx["normalized_text"]):
            return

        if await handle_owner_commands(message, ctx["normalized_text"]):
            return

        # Публичные команды "др" и "пары":
        # - доступны всем в беседе CHAT_ID (при упоминании бота или ответе ему)
        # - доступны владельцу также в ЛС
        if await handle_public_commands(message, ctx):
            return

    # Обрабатываем только текстовые сообщения для LLM
    if not message.text:
        return

    # Если это другая группа (не основная) и пришли ключевые команды — вежливо отказываем, не зовем LLM
    if ctx:
        if (
            message.chat.type in ("group", "supergroup")
            and not ctx["is_group_main"]
            and not (message.from_user and message.from_user.id == OWNER_CHAT_ID)
            and (ctx["is_mention"] or ctx["is_reply"])
        ):
            blocked_cmd = is_public_command(ctx["normalized_text"])
            if blocked_cmd:
                user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
                _log(f"GR; От {user_login_log} ({message.from_user.full_name}): команда '{ctx['normalized_text']}' в чужой группе — отклонено")
                deny_text, deny_entities = make_custom_emoji_payload(
                    "❌ <b>Эта команда доступна в основной беседе или в ЛС для пользователей из списка группы.</b>",
                    EMOJI_ID_CROSS,
                )
                try:
                    await message.answer(deny_text, parse_mode="HTML", entities=deny_entities)
                except Exception:
                    try:
                        await message.answer(deny_text, parse_mode="HTML")
                    except Exception:
                        pass
                return

    if message.chat.type == "private":
        await handle_private_chat(message, bot_username, bot_info.id)
    else:
        await handle_group_chat(message, bot_username, bot_info.id)

def register_chat_handlers(dp):
    """
    Регистрирует обработчики чата в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(on_mention_or_reply)
