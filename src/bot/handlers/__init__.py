# Пакет handlers содержит обработчики сообщений Telegram бота
# chat.py - обработка обычных сообщений и упоминаний
# commands.py - обработка команд бота (/start, /help и т.д.)
# chat_member.py - апдейты участников беседы (выход/исключение → чистка пинг-листа)
from src.bot.handlers.commands import register_command_handlers
from src.bot.handlers.chat import register_chat_handlers
from src.bot.handlers.chat_member import register_chat_member_handlers

def register_handlers(dp):
    """
    Регистрирует все обработчики в диспетчере.

    Args:
        dp: Диспетчер aiogram
    """
    register_command_handlers(dp)
    register_chat_member_handlers(dp)
    register_chat_handlers(dp)
