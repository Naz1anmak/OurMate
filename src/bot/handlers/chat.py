"""
Обработчики чата.
Содержит функции для обработки обычных сообщений и упоминаний бота.
"""

import asyncio
import random
from aiogram.types import Message
from aiogram.enums import ChatAction

from src.config.settings import PROMPT_TEMPLATE_CHAT, OWNER_CHAT_ID, CHAT_ID, TIMEZONE
from src.bot.services.llm_service import LLMService
from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.bot.services.schedule_service import schedule_service
from src.utils.text_utils import get_first_name_by_user_id
from src.utils.date_utils import format_birthday_date
from src.bot.handlers.owner_commands import handle_owner_command
from src.utils.log_utils import log_with_ts as _log


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
    bot_info = await bot.get_me()
    bot_username = f"@{bot_info.username}"
    
    # Команды: help/команды доступны всем; остальные — только владельцу
    if message.text:

        help_commands = {"help", "команды"}
        if normalized_text in help_commands:
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            tag = "GR" if message.chat.type in ("group", "supergroup") else "PM"
            _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос '{normalized_text}'")

            base_help = (
                "Доступные команды в беседе:\n\n"
                "• <code>др</code> — ближайший день рождения\n"
                "• <code>др &lt;user_id&gt;</code> или <code>др @username</code> — дата рождения по id или username\n"
                "• <code>пары</code> — пары на сегодня\n"
                "• <code>пары завтра</code> — пары на завтра\n"
                "• <code>отписаться</code> — отключить поздравления (в ЛС с ботом)\n"
                "• <code>help</code> или <code>команды</code> — справка по командам\n\n"
                "<i>❕ Команды работают при упоминании бота или ответе на его сообщение.</i>\n"
                "<i>💡 Чтобы получать поздравления, напишите боту любое сообщение в личные сообщения.</i>"
            )

            if message.from_user.id == OWNER_CHAT_ID:
                admin_block = (
                    "\n\n<b>Админские команды:</b>\n"
                    "• <code>logs</code> — логи бота\n"
                    "• <code>full logs</code> — полные логи\n"
                    "• <code>status</code> — статус службы\n"
                    "• <code>system</code> — информация о системе\n"
                    "• <code>stop bot</code> — остановить бота\n"
                    "• <code>проверка ссылок</code> — диагностика ссылок/активации"
                )
                await message.answer(base_help + admin_block, parse_mode="HTML")
            else:
                await message.answer(base_help, parse_mode="HTML")
            return
        
        # Команда отписаться (только в ЛС)
        if normalized_text == "отписаться":
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            in_group = message.chat.type in ("group", "supergroup")
            tag_unsub = "GR" if in_group else "PM"
            if in_group:
                _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): запрос 'отписаться' в группе — отклонено")
                await message.reply(
                    "❌ Эта команда доступна только в личных сообщениях с ботом.",
                    parse_mode="HTML",
                )
                return
            else:
                _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): запрос 'отписаться'")

            user = next((u for u in birthday_service.users if u.user_id == message.from_user.id), None)
            if user:
                if user.interacted_with_bot:
                    user.interacted_with_bot = False
                    _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): успешная отписка от поздравлений")
                    birthday_service.save_users()
                    await message.answer(
                        "✅ Вы отписались от поздравлений.\n\n"
                        "Чтобы снова получать поздравления, напишите боту любое сообщение.",
                        parse_mode="HTML",
                    )
                else:
                    _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): повторная отписка от поздравлений")
                    await message.answer(
                        "ℹ️ Вы и так не подписаны на поздравления.\n\n"
                        "Чтобы получать поздравления, напишите боту любое сообщение.",
                        parse_mode="HTML",
                    )
            else:
                _log(f"{tag_unsub}; Бот: пользователь {user_login_log or message.from_user.id} не найден в списке пользователей")
                await message.answer(
                    "❌ Вы не найдены в списке пользователей.",
                    parse_mode="HTML",
                )
            return

        owner_commands = {
            "logs",
            "full logs",
            "stop bot",
            "status",
            "system",
            "проверка ссылок",
        }
        if normalized_text in owner_commands:
            # Если пишет не владелец — отказываем
            if message.from_user.id != OWNER_CHAT_ID:
                user_login = f"@{message.from_user.username}" if message.from_user.username else ""
                if message.chat.type in ("group", "supergroup"):
                    _log(f"GR; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
                else:
                    _log(f"PM; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
                await message.answer(
                    "❌ <b>В доступе отказано</b>\n\nЭта команда доступна только владельцу бота.",
                    parse_mode="HTML",
                )
                return
            # Если это владелец (в ЛС или в группе), передаем обработку специализированному хендлеру
            if await handle_owner_command(message):
                return

    # Публичные команды "др" и "пары":
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
        is_private_non_owner = (
            message.chat.type == "private" and message.from_user and message.from_user.id != OWNER_CHAT_ID
        )
        
        is_group_trigger = is_group_context and (is_mention or is_reply)
        should_process_birthday_command = is_owner_pm or is_group_trigger
        should_process_schedule_command = is_owner_pm or is_group_trigger

        # Запрещаем публичные команды в ЛС для не-владельца, чтобы не уходить в LLM
        if is_private_non_owner and (
            normalized_text == "др"
            or normalized_text.startswith("др ")
            or normalized_text == "пары"
            or normalized_text == "пары завтра"
        ):
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            _log(
                f"PM; От {user_login_log} ({message.from_user.full_name}): попытка команды '{normalized_text}' — отклонено (не владелец)"
            )
            await message.reply(
                "❌ <b>Эта команда доступна только в беседе при упоминании бота.</b>\n\n" \
                "В ЛС доступны <code>help</code>/<code>команды</code> и <code>отписаться</code>.",
                parse_mode="HTML",
            )
            return

        if normalized_text == "др" and should_process_birthday_command:
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            tag = "GR" if is_group_context else "PM"
            _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др'")
            
            # В ЛС владельца — одно уведомление, в беседе — другое
            if is_owner_pm:
                # ЛС владельца
                notification = birthday_service.get_next_birthday_notification(TIMEZONE)
            else:
                # Беседа
                notification = birthday_service.get_next_birthday_notification_for_group(TIMEZONE)
            
            if notification:
                await message.bot.send_message(
                    message.chat.id,
                    notification,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await message.answer("Нет данных о следующем дне рождения")
            return

        if normalized_text.startswith("др ") and should_process_birthday_command:
            parts = text_for_commands.strip().split()
            target_id = None
            target_username = None

            if len(parts) >= 2:
                arg = parts[1]
                if arg.isdigit():
                    target_id = int(arg)
                else:
                    target_username = arg.lstrip("@")

            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            tag = "GR" if is_group_context else "PM"

            if target_id is None:
                lookup = target_username or ""
                if not lookup:
                    _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др' без аргумента")
                    await message.reply("Укажи user_id или @username (др 123456 или др @user). Команда срабатывает по упоминанию бота или ответу на его сообщение.")
                    return
                found_user = next(
                    (u for u in birthday_service.users if u.username and u.username.lower() == lookup.lower()),
                    None,
                )
                _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др @{lookup}'")
            else:
                found_user = next((u for u in birthday_service.users if u.user_id == target_id), None)
                _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др {target_id}'")

            search_value = str(target_id) if target_id is not None else f"@{lookup}"
            if found_user:
                pretty_date = format_birthday_date(found_user.birthday)
                username_info = f" (@{found_user.username})" if found_user.username else ""
                await message.reply(
                    f"{found_user.mention_html()}{username_info} отмечает день рождения {pretty_date}",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                _log(
                    f"{tag}; Бот: пользователь не найден в списке дней рождения по запросу '{search_value}' (запрос от {user_login_log} ({message.from_user.full_name}))"
                )
                await message.reply("Пользователь не найден в списке дней рождения")
            return
        
        no_pairs_today = [
            "Пар сегодня нет, отдыхайте родные!",
            "Пар сегодня нет, берите кофе и отдыхайте!",
            "Пар сегодня нет, самое время заняться своими делами!",
            "Пар сегодня нет, но можно повторить материал 😉",
            "Пар сегодня нет, ловите передышку!",
            "Пар сегодня нет, если что — я рядом!",
        ]

        no_pairs_tomorrow = [
            "Пар завтра нет, отдыхайте родные!",
            "Пар завтра нет, наслаждайтесь свободным днем!",
            "Пар завтра нет, самое время выспаться!",
            "Пар завтра нет, планируйте свой день как хотите!",
            "Пар завтра нет, удачного вам дня!",
            "Пар завтра нет, но я бы на вашем месте все равно бы поучился!",
            "Пар завтра нет, но я всегда на связи, родные!",
        ]

        # Пары сегодня
        if normalized_text == "пары" and should_process_schedule_command:
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            _log(f"GR; От {user_login_log} ({message.from_user.full_name}): запрос 'пары'")
            events = schedule_service.get_todays_classes(TIMEZONE)
            empty_text = random.choice(no_pairs_today)
            text = schedule_service.format_classes(events, "📚 Пары на сегодня:", empty_text)
            await message.reply(text, parse_mode="HTML")
            return

        # Пары завтра
        if normalized_text == "пары завтра" and should_process_schedule_command:
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            _log(f"GR; От {user_login_log} ({message.from_user.full_name}): запрос 'пары завтра'")
            events = schedule_service.get_tomorrows_classes(TIMEZONE)
            empty_text = random.choice(no_pairs_tomorrow)
            text = schedule_service.format_classes(events, "📚 Пары на завтра", empty_text)
            await message.reply(text, parse_mode="HTML")
            return

    # Обрабатываем только текстовые сообщения для LLM
    if not message.text:
        return

    # Если это другая группа (не основная) и пришли ключевые команды — вежливо отказываем, не зовем LLM
    if message.chat.type in ("group", "supergroup") and not is_group_context and (is_mention or is_reply):
        blocked_cmd = (
            normalized_text == "др"
            or normalized_text.startswith("др ")
            or normalized_text == "пары"
            or normalized_text == "пары завтра"
        )
        if blocked_cmd:
            user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
            _log(f"GR; От {user_login_log} ({message.from_user.full_name}): команда '{normalized_text}' в чужой группе — отклонено")
            await message.reply(
                "❌ <b>Эта команда доступна только в основной беседе.</b>",
                parse_mode="HTML",
            )
            return

    chat_id = message.chat.id
    text = message.text or ""
    # bot, bot_info, bot_username уже получены выше для команд "др"

    # Проверяем, нужно ли обрабатывать это сообщение
    if not _should_process_message(message, bot_username, bot_info.id):
        return

    # Получаем логин пользователя
    user_login = _extract_user_login(message, text, bot_username)
    
    # Находим имя пользователя по user_id
    first_name = get_first_name_by_user_id(message.from_user.id, birthday_service.users)
    
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
        _log(f"GR; От {user_login} ({message.from_user.full_name}): {original_text}")
        _log(f"GR; Бот (LLM): {final_answer}")
        await message.reply(final_answer, parse_mode="HTML")
    else:
        _log(f"PM; От {user_login} ({message.from_user.full_name}): {original_text}")
        _log(f"PM; Бот (LLM): {final_answer}")
        await message.answer(final_answer, parse_mode="HTML")


def register_chat_handlers(dp):
    """
    Регистрирует обработчики чата в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(on_mention_or_reply)
