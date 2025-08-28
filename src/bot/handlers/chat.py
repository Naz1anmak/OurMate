"""
Обработчики чата.
Содержит функции для обработки обычных сообщений и упоминаний бота.
"""

from pprint import pprint
import asyncio
from aiogram.types import Message
from aiogram.enums import ChatAction

from src.config.settings import PROMPT_TEMPLATE_CHAT, OWNER_CHAT_ID, CHAT_ID, TIMEZONE
from src.bot.services.llm_service import LLMService
from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.utils.text_utils import get_first_name_by_login
from src.utils.date_utils import format_birthday_date
from src.bot.handlers.owner_commands import handle_owner_command


async def on_mention_or_reply(message: Message):
    """
    Обработчик для упоминаний бота и ответов на его сообщения.
    Обрабатывает сообщения в группах и личных чатах.
    
    Args:
        message (Message): Входящее сообщение
    """
    # Инициализируем переменные бота в начале функции
    bot = message.bot
    bot_info = await bot.get_me()
    bot_username = f"@{bot_info.username}"
    
    # Команды владельца перехватываются ниже (с проверкой прав)

    # Блокируем все команды владельца для не-владельцев, чтобы не уходили в LLM
    if message.text:
        normalized_text = message.text.lower().strip()
        owner_commands = {
            "help",
            "команды",
            "logs",
            "full logs",
            "stop bot",
            "status",
            "system",
        }
        if normalized_text in owner_commands:
            # Если пишет не владелец — отказываем
            if message.from_user.id != OWNER_CHAT_ID:
                user_login = f"@{message.from_user.username}" if message.from_user.username else ""
                if message.chat.type in ("group", "supergroup"):
                    print(f"GR; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
                else:
                    print(f"PM; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
                await message.answer(
                    "❌ <b>В доступе отказано</b>\n\nЭти команды доступны только владельцу бота.",
                    parse_mode="HTML",
                )
                return
            # Если это владелец (в ЛС или в группе), передаем обработку специализированному хендлеру
            if await handle_owner_command(message):
                return

    # Публичные команды "др" и "др @username":
    # - доступны всем в беседе CHAT_ID (при упоминании бота или ответе ему)
    # - доступны владельцу также в ЛС
    if message.text:
        # Получаем информацию о боте для проверки упоминаний
        # bot, bot_info, bot_username уже получены выше
        
        # Проверяем упоминания и ответы
        is_mention = any(token == bot_username for token in message.text.split())
        is_reply = (message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id)
        
        # Нормализуем текст, убирая упоминание бота
        text_for_commands = message.text
        if is_mention:
            # Убираем упоминание бота из текста для проверки команд
            text_for_commands = " ".join([token for token in message.text.split() if token != bot_username])
        
        normalized_text = text_for_commands.lower().strip()
        
        is_group_context = (
            message.chat.type in ("group", "supergroup") and message.chat.id == CHAT_ID
        )
        is_owner_pm = (
            message.chat.type == "private" and message.from_user and message.from_user.id == OWNER_CHAT_ID
        )
        
        should_process_birthday_command = (
            is_owner_pm or 
            (is_group_context and (is_mention or is_reply))
        )

        if normalized_text == "др" and should_process_birthday_command:
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            tag = "GR" if is_group_context else "PM"
            print(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др'")
            notification = birthday_service.get_next_birthday_notification(TIMEZONE)
            await message.reply(notification or "Нет данных о следующем дне рождения")
            return

        if normalized_text.startswith("др ") and should_process_birthday_command:
            # Используем очищенный текст для поиска логина
            parts = text_for_commands.strip().split()
            if len(parts) >= 2 and parts[1].startswith("@"):
                query_login = parts[1]
                found_user = None
                for user in birthday_service.users:
                    if user.user_login and user.user_login.lower() == query_login.lower():
                        found_user = user
                        break
                user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
                tag = "GR" if is_group_context else "PM"
                print(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др {query_login}'")
                if found_user:
                    pretty_date = format_birthday_date(found_user.birthday)
                    await message.reply(f"{found_user.name} отмечает день рождения {pretty_date}")
                else:
                    await message.reply("Пользователь не найден в списке дней рождения")
                return

    # Обрабатываем только текстовые сообщения для LLM
    if not message.text:
        return
        
    chat_id = message.chat.id
    text = message.text or ""
    # bot, bot_info, bot_username уже получены выше для команд "др"

    # Проверяем, нужно ли обрабатывать это сообщение
    if not _should_process_message(message, bot_username, bot_info.id):
        return

    # Получаем логин пользователя
    user_login = _extract_user_login(message, text, bot_username)
    
    # Находим имя пользователя по логину
    first_name = get_first_name_by_login(user_login, birthday_service.users)
    
    # Формируем сообщения для LLM
    messages = _build_llm_messages(chat_id, text)

    # Временное сообщение о том, что бот думает над ответом
    temp_msg = None
    try:
        temp_msg = await message.reply("🧠 Мне понадобится немного времени, думаю над ответом...")
    except Exception:
        temp_msg = None

    # Эффект "печатает..." и запрос к LLM без блокировки event loop
    stop_event = asyncio.Event()

    async def _typing_indicator():
        try:
            while not stop_event.is_set():
                await message.bot.send_chat_action(message.chat.id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except Exception:
            # Безопасно игнорируем ошибки индикатора
            pass

    typing_task = asyncio.create_task(_typing_indicator())
    try:
        # Выполняем синхронный HTTP-запрос в пуле потоков
        answer_body = await asyncio.to_thread(LLMService.send_chat_request, messages)
    finally:
        stop_event.set()
        try:
            await typing_task
        except Exception:
            pass
    
    # Сохраняем контекст
    context_service.save_context(chat_id, message.text, answer_body)
    
    # Формируем финальный ответ
    final_answer = _format_final_answer(first_name, answer_body)
    
    # Экранируем HTML для безопасной отправки
    import html
    safe_answer = html.escape(final_answer)
    
    # Удаляем временное сообщение перед отправкой ответа
    if temp_msg:
        try:
            await temp_msg.delete()
        except Exception:
            pass
    
    # Отправляем ответ
    await _send_response(message, safe_answer, user_login, text)


def _should_process_message(message: Message, bot_username: str, bot_id: int) -> bool:
    """
    Проверяет, нужно ли обрабатывать сообщение.
    
    Args:
        message (Message): Сообщение для проверки
        bot_username (str): Имя бота с @
        bot_id (int): ID бота
        
    Returns:
        bool: True, если сообщение нужно обработать
    """
    # В личных сообщениях обрабатываем все
    if message.chat.type not in ("group", "supergroup"):
        return True
    
    # В группе обрабатываем только упоминания или ответы на сообщения бота
    # Проверяем точное упоминание бота через @username
    is_mention = any(token == bot_username for token in (message.text or "").split())
    is_reply = (
        message.reply_to_message
        and message.reply_to_message.from_user.id == bot_id
    )
    
    return is_mention or is_reply


def _extract_user_login(message: Message, text: str, bot_username: str) -> str:
    """
    Извлекает логин пользователя из сообщения.
    
    Args:
        message (Message): Сообщение
        text (str): Текст сообщения
        bot_username (str): Имя бота с @
        
    Returns:
        str: Логин пользователя или пустая строка
    """
    # Если это ответ на сообщение бота, берем логин того, кто отвечает
    if message.from_user and message.from_user.username:
        return "@" + message.from_user.username
    
    # Иначе ищем упоминания в тексте (кроме самого бота)
    if any(token == bot_username for token in text.split()):
        for token in text.split():
            if token.startswith("@") and token != bot_username:
                return token
    
    return ""


def _build_llm_messages(chat_id: int, current_text: str) -> list:
    """
    Формирует список сообщений для отправки в LLM.
    
    Args:
        chat_id (int): ID чата
        current_text (str): Текущий текст сообщения
        
    Returns:
        list: Список сообщений для LLM
    """
    messages = [
        {
            "role": "system",
            "content": PROMPT_TEMPLATE_CHAT
        }
    ]
    
    # Добавляем предыдущий контекст, если есть
    prev_context = context_service.get_context(chat_id)
    if prev_context:
        messages.append({"role": "user", "content": prev_context[0]})
        messages.append({"role": "assistant", "content": prev_context[1]})
    
    # Добавляем текущий запрос
    messages.append({"role": "user", "content": current_text})
    
    return messages


def _format_final_answer(first_name: str, answer_body: str) -> str:
    """
    Форматирует финальный ответ с обращением по имени.
    
    Args:
        first_name (str): Имя пользователя
        answer_body (str): Основной ответ от LLM
        
    Returns:
        str: Отформатированный ответ
    """
    if first_name:
        # Если нашли имя, добавляем обращение в начале
        return f"{first_name}, {answer_body[:1].lower() + answer_body[1:]}"
    else:
        return answer_body


async def _send_response(message: Message, final_answer: str, user_login: str, original_text: str):
    """
    Отправляет ответ пользователю.
    
    Args:
        message (Message): Исходное сообщение
        final_answer (str): Ответ для отправки
        user_login (str): Логин пользователя
        original_text (str): Исходный текст
    """
    # Логируем сообщение
    if message.chat.type in ("group", "supergroup"):
        pprint(f"GR; От {user_login} ({message.from_user.full_name}): {original_text}")
        await message.reply(final_answer, parse_mode="HTML")
    else:
        pprint(f"PM; От {user_login} ({message.from_user.full_name}): {original_text}")
        await message.answer(final_answer, parse_mode="HTML")


def register_chat_handlers(dp):
    """
    Регистрирует обработчики чата в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(on_mention_or_reply)
