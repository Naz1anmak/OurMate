"""
Обработчики команд владельца бота.
Позволяет владельцу управлять сервером через Telegram.
"""
import asyncio
import subprocess
from aiogram.types import Message

from src.config.settings import OWNER_CHAT_ID
from src.bot.services.system_service import system_service
from src.bot.services.birthday_service import birthday_service
from src.utils.log_utils import log_with_ts as _log

# Набор команд, доступных только владельцу
OWNER_COMMANDS = {
    "logs",
    "full logs",
    "stop bot",
    "status",
    "system",
    "проверка ссылок",
}

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
    _log(f"{tag}; От {user_login} ({message.from_user.full_name}): запрос '{message.text}'")
    
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
    
    elif text == "проверка ссылок":
        # Диагностика: гиперссылка + активация бота
        lines = ["🔍 <b>Проверка ссылок и активации:</b>\n"]

        for user in birthday_service.users:
            mention = user.mention_html()  # дает ссылку, если есть user_id
            username_info = f" (@{user.username})" if user.username else ""

            # Эмодзи-сигналы:
            #  - статус: ✅ для active, 🚫 для прочих
            #  - ссылка/наличие id: если user_id нет — ⭕️
            #  - активация: 🎂 если писал боту (только при наличии user_id)
            if user.user_id is None:
                prefix = "⭕️"
            else:
                prefix = "✅" if user.status == "active" else "🚫"

            has_cake = user.user_id is not None and user.interacted_with_bot
            if has_cake:
                prefix = f"{prefix}🎂"

            # Если есть тортик — сразу печатаем имя без пробела и тире
            if has_cake:
                lines.append(f"{prefix}{mention}{username_info}")
            else:
                lines.append(f"{prefix} — {mention}{username_info}")

        response = "\n".join(lines)

        await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)
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
    • <code>др 123456789</code> — дата дня рождения пользователя (в беседе и в ЛС владельца)

    <b>Диагностика:</b>
    • <code>проверка ссылок</code> - Проверить ссылки и активацию пользователей (владелец)

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
