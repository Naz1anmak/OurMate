"""
Обработчики команд бота.
Содержит функции для обработки команд типа /start, /help и т.д.
"""

from aiogram import types
from aiogram.filters import Command


async def cmd_start(message: types.Message):
    """
    Обработчик команды /start.
    Отправляет приветственное сообщение пользователю.
    
    Args:
        message (types.Message): Сообщение с командой
    """
    # Логируем информацию о пользователе
    user_login = f"@{message.from_user.username}" if message.from_user.username else ""
    print(f"FP; От {user_login} ({message.from_user.full_name}): /start")
    
    # Проверяем, является ли пользователь владельцем
    from src.config.settings import OWNER_CHAT_ID
    
    if message.from_user.id == OWNER_CHAT_ID:
        # Сообщение для владельца
        welcome_text = """
🤖 <b>Привет, владелец!</b>

Я бот с подключенной нейросетью. Помимо обычного чата, у вас есть доступ к специальным командам:

<b>Команды управления:</b>
• <code>logs</code> - Логи бота
• <code>full logs</code> - Полные логи
• <code>status</code> - Статус службы
• <code>system</code> - Информация о системе
• <code>stop bot</code> - Остановить бота
• <code>help</code> - Справка по командам

<b>Команды по дням рождения:</b>
• <code>др</code> — ближайший день рождения (в беседе и в ЛС владельца)
• <code>др @username</code> — дата дня рождения пользователя (в беседе и в ЛС владельца)

<b>Обычный чат:</b>
Просто напишите мне сообщение, и я отвечу с помощью нейросети.
        """
    else:
        # Сообщение для обычных пользователей
        welcome_text = """
🤖 <b>Привет!</b>

Я бот с подключенной нейросетью. Чтобы задать мне вопрос — просто напиши его тут, а в группе упомяни меня через @ или ответь на моё сообщение.

💬 Я запоминаю контекст наших диалогов, поэтому могу поддерживать осмысленную беседу.

<b>В группе доступно для всех:</b>
• <code>др</code> — ближайший день рождения
• <code>др @username</code> — дата дня рождения пользователя
<i>Нужно упомянуть бота или ответить на его сообщение.</i>

<b>Хотите больше функций?</b>
Если вам нужны автоматические поздравления с днями рождения в вашей беседе и уведомления о будущих днях рождения, вы можете клонировать этот бот и настроить под себя:

🔗 <a href="https://github.com/Naz1anmak/OurMate">GitHub репозиторий</a>
        """
    
    await message.answer(welcome_text, parse_mode="HTML")

def register_command_handlers(dp):
    """
    Регистрирует обработчики команд в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(cmd_start, Command("start"))
