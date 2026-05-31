"""
Обработчики чата.
Содержит функции для обработки обычных сообщений и упоминаний бота.
"""
import logging

from aiogram.types import Message

from src.bot.services.birthday_service import birthday_service
from src.bot.handlers.chat_context import build_command_context
from src.bot.handlers.chat_commands import (
    handle_help_command,
    handle_unsubscribe_command,
    handle_public_commands,
)
from src.bot.handlers.owner_commands import handle_owner_command
from src.bot.handlers import access
from src.bot.handlers.chat_pm import handle_private_chat
from src.bot.handlers.chat_group import handle_group_chat
from src.utils.telegram_cache import (
    get_cached_bot_identity,
    get_cached_bot_info,
    get_cached_bot_username,
)

logger = logging.getLogger(__name__)

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
            logger.warning("bot.get_me() недоступен: %s", exc)
            return
        bot_info = cached_info
        cached_username = get_cached_bot_username()
    bot_username = cached_username or f"@{bot_info.username}"
    ctx = build_command_context(message, bot_username, bot_info.id) if message.text else None

    # В группе бот реагирует только на упоминание/реплай — единый триггер-гейт.
    if message.chat.type in ("group", "supergroup") and not access.detect_trigger(
        message, bot_username, bot_info.id
    ):
        return

    if ctx:
        audience = access.classify(ctx["normalized_text"])
        if audience is not None:
            decision = access.resolve(audience, ctx)
            if not decision.allowed:
                await access.send_denial(message, decision.denial)
                return
            if audience is access.Audience.EVERYONE:
                await handle_help_command(message, ctx["normalized_text"])
            elif audience is access.Audience.UNSUBSCRIBE:
                await handle_unsubscribe_command(message, ctx["normalized_text"])
            elif audience is access.Audience.OWNER:
                await handle_owner_command(message)
            else:  # Audience.PUBLIC / GROUP_OR_OWNER → общий роутер команд
                await handle_public_commands(message, ctx)
            return

    # Не команда → LLM (только текст).
    if not message.text:
        return

    if message.chat.type == "private":
        await handle_private_chat(message, bot_username, bot_info.id, ctx)
    else:
        await handle_group_chat(message, bot_username, bot_info.id, ctx)

def register_chat_handlers(dp):
    """
    Регистрирует обработчики чата в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(on_mention_or_reply)
