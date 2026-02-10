"""
Обработчики чата.
Содержит функции для обработки обычных сообщений и упоминаний бота.
"""
import asyncio
import random
from datetime import datetime, date
from aiogram.types import Message
from aiogram.enums import ChatAction

from src.config.settings import PROMPT_TEMPLATE_CHAT, OWNER_CHAT_ID, CHAT_ID, TIMEZONE
from src.bot.services.llm_service import LLMService, LLMServiceError
from src.bot.services.context_service import context_service
from src.bot.services.birthday_service import birthday_service
from src.bot.services.schedule_service import schedule_service
from src.utils.text_utils import get_first_name_by_user_id
from src.utils.date_utils import format_birthday_date
from src.bot.handlers.owner_commands import handle_owner_command, OWNER_COMMANDS
from src.utils.log_utils import log_with_ts as _log
from src.utils.render_utils import render_html_with_code
from src.utils.telegram_cache import (
    get_cached_bot_identity,
    get_cached_bot_info,
    get_cached_bot_username,
)

def _is_public_command(text: str) -> bool:
    """Возвращает True для публичных команд др/пары."""
    return (
        text == "др"
        or text.startswith("др ")
        or text == "пары"
        or text == "пары завтра"
    )

def _build_command_context(message: Message, bot_username: str, bot_id: int) -> dict:
    text = message.text or ""
    is_mention = any(token == bot_username for token in text.split())
    is_reply = (
        message.reply_to_message
        and message.reply_to_message.from_user.id == bot_id
    )

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

async def _handle_help_command(message: Message, normalized_text: str) -> bool:
    help_commands = {"help", "команды"}
    if normalized_text not in help_commands:
        return False

    user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
    tag = "GR" if message.chat.type in ("group", "supergroup") else "PM"
    _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос '{normalized_text}'")

    base_help = (
        "<b>Доступные команды:</b>\n\n"
        "• <code>др</code> — ближайший день рождения\n"
        "• <code>др &lt;id&gt;</code> или <code>др @username</code> — дата дня рождения по id или username\n"
        "• <code>пары</code> — пары на сегодня\n"
        "• <code>пары завтра</code> — пары на завтра\n"
        "• <code>отписаться</code> — отключить поздравления (в ЛС с ботом)\n"
        "• <code>help</code> или <code>команды</code> — справка по командам\n\n"
        "<i>❕ В беседе команды работают при упоминании бота или ответе на его сообщение.</i>\n"
        "<i>💡 В ЛС команды доступны владельцу и пользователям из списка группы.</i>\n"
    )

    if message.from_user.id == OWNER_CHAT_ID:
        admin_block = (
            "\n<b>Админские команды:</b>\n"
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
    return True

async def _handle_unsubscribe_command(message: Message, normalized_text: str) -> bool:
    if normalized_text != "отписаться":
        return False

    user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
    in_group = message.chat.type in ("group", "supergroup")
    tag_unsub = "GR" if in_group else "PM"
    if in_group:
        _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): запрос 'отписаться' в группе — отклонено")
        await message.answer(
            "❌ Эта команда доступна только в личных сообщениях с ботом.",
            parse_mode="HTML",
        )
        return True
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
    return True

async def _handle_owner_commands(message: Message, normalized_text: str) -> bool:
    if normalized_text not in OWNER_COMMANDS:
        return False

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
        return True

    # Если это владелец (в ЛС или в группе), передаем обработку специализированному хендлеру
    if await handle_owner_command(message):
        return True
    # Если что-то пошло не так и команда не обработалась — не пускаем дальше в LLM
    return True

async def _handle_public_commands(message: Message, ctx: dict) -> bool:
    normalized_text = ctx["normalized_text"]
    text_for_commands = ctx["text_for_commands"]
    is_group_chat = ctx["is_group_chat"]

    # Запрещаем публичные команды в ЛС для не-владельца, чтобы не уходить в LLM
    if ctx["is_private_non_owner"] and not ctx["is_whitelisted_private"] and _is_public_command(normalized_text):
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        _log(
            f"PM; От {user_login_log} ({message.from_user.full_name}): попытка команды '{normalized_text}' — отклонено (нет в списке)"
        )
        await message.answer(
            "❌ <b>Эта команда доступна только избранным пользователям.</b>",
            parse_mode="HTML",
        )
        return True

    if normalized_text == "др" and ctx["should_process_birthday_command"]:
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if is_group_chat else "PM"
        _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др'")

        # В ЛС владельца — одно уведомление, в беседе — другое
        if ctx["is_owner_pm"]:
            notification = birthday_service.get_next_birthday_notification(TIMEZONE)
        else:
            notification = birthday_service.get_next_birthday_notification(TIMEZONE)

        if notification:
            await message.bot.send_message(
                message.chat.id,
                notification,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            await message.answer("Нет данных о следующем дне рождения")
        return True

    if normalized_text.startswith("др ") and ctx["should_process_birthday_command"]:
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
        tag = "GR" if is_group_chat else "PM"

        if target_id is None:
            lookup = target_username or ""
            if not lookup:
                _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др' без аргумента")
                await message.answer("Укажи user_id или @username (др 123456 или др @user). Команда срабатывает по упоминанию бота или ответу на его сообщение.")
                return True
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
            await message.answer(
                f"{found_user.mention_html()}{username_info} отмечает день рождения {pretty_date}",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            _log(
                f"{tag}; Бот: пользователь не найден в списке дней рождения по запросу '{search_value}' (запрос от {user_login_log} ({message.from_user.full_name}))"
            )
            await message.answer("Пользователь не найден в списке дней рождения")
        return True

    if normalized_text == "пары" and ctx["should_process_schedule_command"]:
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if ctx["is_group_chat"] else "PM"
        _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'пары'")
        effective_date = schedule_service.get_effective_date(TIMEZONE)
        events = schedule_service.get_classes_for_date(effective_date)
        today = datetime.now(TIMEZONE).date()
        day_label = "завтра" if effective_date == date.fromordinal(today.toordinal() + 1) else "сегодня"
        title = "📚 Пары на завтра:" if day_label == "завтра" else "📚 Пары на сегодня:"
        empty_text = schedule_service.get_no_pairs_message(day_label)
        if events:
            text = schedule_service.format_classes(events, title, empty_text, wrap_quote=True)
        else:
            next_date, next_events = schedule_service.get_next_classes_after(effective_date)
            if next_date and next_events:
                next_block = schedule_service.format_next_classes_block(next_date, next_events, base_date=effective_date)
                text = f"{empty_text}\n\n{next_block}"
            else:
                text = empty_text
        await message.answer(text, parse_mode="HTML")
        return True

    if normalized_text == "пары завтра" and ctx["should_process_schedule_command"]:
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if ctx["is_group_chat"] else "PM"
        _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'пары завтра'")
        events = schedule_service.get_tomorrows_classes(TIMEZONE)
        empty_text = schedule_service.get_no_pairs_message("завтра")
        if events:
            text = schedule_service.format_classes(events, "📚 Пары на завтра:", empty_text, wrap_quote=True)
        else:
            base_date = date.fromordinal(datetime.now(TIMEZONE).date().toordinal() + 1)
            next_date, next_events = schedule_service.get_next_classes_after(base_date)
            if next_date and next_events:
                next_block = schedule_service.format_next_classes_block(next_date, next_events, base_date=base_date)
                text = f"{empty_text}\n\n{next_block}"
            else:
                text = empty_text
        await message.answer(text, parse_mode="HTML")
        return True

    return False

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
    ctx = _build_command_context(message, bot_username, bot_info.id) if message.text else None

    # Команды: help/команды доступны всем; остальные — только владельцу
    if ctx:
        if await _handle_help_command(message, ctx["normalized_text"]):
            return

        if await _handle_unsubscribe_command(message, ctx["normalized_text"]):
            return

        if await _handle_owner_commands(message, ctx["normalized_text"]):
            return

        # Публичные команды "др" и "пары":
        # - доступны всем в беседе CHAT_ID (при упоминании бота или ответе ему)
        # - доступны владельцу также в ЛС
        if await _handle_public_commands(message, ctx):
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
            blocked_cmd = _is_public_command(ctx["normalized_text"])
            if blocked_cmd:
                user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
                _log(f"GR; От {user_login_log} ({message.from_user.full_name}): команда '{ctx['normalized_text']}' в чужой группе — отклонено")
                await message.answer(
                    "❌ <b>Эта команда доступна в основной беседе или в ЛС для пользователей из списка группы.</b>",
                    parse_mode="HTML",
                )
                return

    chat_id = message.chat.id
    text = message.text or ""
    text_for_llm = _strip_bot_mention(text, bot_username)
    # bot, bot_info, bot_username уже получены выше для команд "др"

    # Проверяем, нужно ли обрабатывать это сообщение
    if not _should_process_message(message, bot_username, bot_info.id):
        return

    # Получаем логин пользователя
    user_login = _extract_user_login(message, text, bot_username)
    tag = "GR" if message.chat.type in ("group", "supergroup") else "PM"
    user_login_safe = user_login or message.from_user.full_name or str(message.from_user.id)
    _log(f"{tag}; От {user_login_safe}: {text_for_llm}")
    
    # Находим имя пользователя по user_id
    first_name = get_first_name_by_user_id(message.from_user.id, birthday_service.users)
    
    # Формируем сообщения для LLM
    messages = _build_llm_messages(chat_id, text_for_llm)

    # Временное сообщение о том, что бот думает над ответом
    thinking_variants = [
        "🧠 Мне понадобится немного времени, думаю над ответом...",
        "⌛ Одну секунду, формулирую мысль...",
        "💭 Обдумываю, чтобы ответить по делу...",
        "✏️ Проверяю факты, сейчас вернусь...",
        "🔎 Сверяю детали, почти готово...",
        "⚙️ Прокручиваю логику в голове...",
        "🧩 Осталась последняя деталь...",
        "🌀 Привожу мысли в порядок...",
        "📚 Освежаю материалы, секунду...",
        "🤔 Хочу ответить точно, чуть-чуть подожди..."
    ]

    temp_msg = None
    try:
        if message.chat.type == "private":
            temp_msg = await message.answer(random.choice(thinking_variants))
        else:
            temp_msg = await message.reply(random.choice(thinking_variants))
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

    answer_body = None
    llm_error = None
    typing_task = asyncio.create_task(_typing_indicator())
    try:
        # Выполняем синхронный HTTP-запрос в пуле потоков
        answer_body = await asyncio.to_thread(LLMService.send_chat_request, messages)
    except LLMServiceError as exc:
        llm_error = f"LLMServiceError: {exc}"
    except Exception as exc:
        llm_error = f"Unexpected LLM error: {exc}"
    finally:
        stop_event.set()
        try:
            await typing_task
        except Exception:
            pass

    if llm_error:
        tag = "GR" if message.chat.type in ("group", "supergroup") else "PM"
        user_login_safe = user_login or message.from_user.full_name or str(message.from_user.id)
        _log(f"{tag}; Бот: LLM недоступен для {user_login_safe}: {llm_error}")
        fallback_text = "⚠️ LLM временно недоступен. Попробуй ещё раз через пару минут."
        if temp_msg:
            try:
                await temp_msg.delete()
            except Exception:
                pass
        try:
            if message.chat.type == "private":
                await message.answer(fallback_text)
            else:
                await message.reply(fallback_text)
        except Exception:
            pass
        owner_notice = (
            "⚠️ LLM недоступен\n"
            f"От: {user_login_safe} (chat_id={chat_id}, type={message.chat.type})\n"
            f"Текст: {text_for_llm[:500]}\n"
            f"Ошибка: {llm_error}"
        )
        try:
            await message.bot.send_message(OWNER_CHAT_ID, owner_notice)
        except Exception:
            pass
        return

    # Сохраняем контекст
    context_service.save_context(chat_id, text_for_llm, answer_body)
    
    # Формируем финальный ответ
    final_answer = _format_final_answer(first_name, answer_body)
    
    # Экранируем текст и выделяем code-блоки
    safe_answer = render_html_with_code(final_answer)
    
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
    prev_pairs = context_service.get_context(chat_id)
    if prev_pairs:
        for question, answer in prev_pairs:
            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": answer})
    
    # Добавляем текущий запрос
    messages.append({"role": "user", "content": current_text})
    
    return messages

def _strip_bot_mention(text: str, bot_username: str) -> str:
    """Убирает прямое упоминание бота, чтобы не попадало в LLM как обращение по логину."""
    if not text:
        return text
    tokens = text.split()
    filtered = [t for t in tokens if t != bot_username]
    # Если убрали упоминание — возвращаем очищенный текст, иначе исходный
    if len(filtered) != len(tokens):
        return " ".join(filtered).strip(" ,")
    # Дополнительно чистим ведущий логин в начале строки
    if text.startswith(bot_username):
        return text[len(bot_username):].strip(" ,")
    return text

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
        _log(f"GR; Бот (LLM): {final_answer}")
        await message.reply(final_answer, parse_mode="HTML")
    else:
        _log(f"PM; Бот (LLM): {final_answer}")
        await message.answer(final_answer, parse_mode="HTML")

def register_chat_handlers(dp):
    """
    Регистрирует обработчики чата в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(on_mention_or_reply)
