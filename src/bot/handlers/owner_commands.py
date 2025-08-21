"""
Обработчики команд владельца бота.
Позволяет владельцу управлять сервером через Telegram.
"""

from aiogram.types import Message
import asyncio
import subprocess

from src.config.settings import OWNER_CHAT_ID
from src.bot.services.system_service import system_service


async def handle_owner_command(message: Message) -> bool:
    """
    Обрабатывает команды владельца бота.
    
    Args:
        message (Message): Сообщение от пользователя
        
    Returns:
        bool: True, если команда была обработана
    """
    # Проверяем, что сообщение от владельца
    if message.from_user.id != OWNER_CHAT_ID:
        return False
    
    # Разрешаем команды владельца в любом типе чата (личка или группа)
    
    text = message.text.lower().strip()
    
    # Логируем команду владельца как PM/GR по месту использования
    user_login = f"@{message.from_user.username}" if message.from_user.username else ""
    tag = "GR" if message.chat.type in ("group", "supergroup") else "PM"
    print(f"{tag}; От {user_login} ({message.from_user.full_name}): запрос '{message.text}'")
    
    # Обрабатываем команды
    if text == "logs":
        response = system_service.get_bot_logs()
        await message.answer(response, parse_mode="HTML")
        return True
    
    elif text == "full logs":
        response = system_service.get_full_logs()
        await message.answer(response, parse_mode="HTML")
        return True
    
    elif text == "stop bot":
        # Сначала сообщаем владельцу, затем останавливаем службу в фоне без логов/ответов
        await message.answer("🛑 <b>Бот останавливается...</b>", parse_mode="HTML")
        async def _stop_service():
            try:
                # Фоновая остановка без захвата вывода, без исключений
                await asyncio.to_thread(
                    subprocess.run,
                    "systemctl stop mybot",
                    shell=True,
                    check=False,
                    capture_output=False,
                    text=True,
                )
            except Exception:
                # Игнорируем любые ошибки — процесс завершится SIGTERM
                pass
        asyncio.create_task(_stop_service())
        return True
    
    elif text == "status":
        response = system_service.get_bot_status()
        await message.answer(response, parse_mode="HTML")
        return True
    
    elif text == "system":
        response = system_service.get_system_info()
        await message.answer(response, parse_mode="HTML")
        return True
    
    elif text == "help" or text == "команды":
        help_text = """
🔧 <b>Команды владельца:</b>

<b>Логи и мониторинг:</b>
• <code>logs</code> - Логи бота (PM, GR, FP сообщения)
• <code>full logs</code> - Полные логи бота
• <code>status</code> - Статус службы бота
• <code>system</code> - Информация о системе

<b>Управление:</b>
• <code>stop bot</code> - Остановить бота

<b>Дни рождения:</b>
• <code>др</code> — ближайший день рождения (в беседе и в ЛС владельца)
• <code>др @username</code> — дата дня рождения пользователя (в беседе и в ЛС владельца)

<b>Справка:</b>
• <code>help</code> или <code>команды</code> - Показать эту справку

        """
        await message.answer(help_text, parse_mode="HTML")
        return True
    
    return False


def register_owner_handlers(dp):
    """
    Регистрирует обработчики команд владельца в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    # Обработчик команд владельца будет вызываться перед обычными обработчиками
    # в функции on_mention_or_reply в chat.py
    pass
