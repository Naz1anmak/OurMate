"""Обработчики команд для чата (общие для PM и групп)."""
from datetime import datetime, date
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from src.config.settings import OWNER_CHAT_ID, TIMEZONE
from src.bot.services.birthday_service import birthday_service
from src.bot.services.schedule_service import schedule_service
from src.utils.date_utils import format_birthday_date
from src.bot.handlers.owner_commands import handle_owner_command, OWNER_COMMANDS
from src.utils.log_utils import log_with_ts as _log
from src.bot.handlers.chat_context import is_public_command

EMOJI_ID_CROSS = "5465665476971471368"
EMOJI_ID_INFO = "5220197908342648622"
EMOJI_ID_IDEA = "5472146462362048818"
EMOJI_ID_CHECK = "5192963112696822273"
EMOJI_ID_INFO_ALT = "5334544901428229844"
EMOJI_ID_BOOKS = "5373098009640836781"

async def handle_help_command(message: Message, normalized_text: str) -> bool:
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
        f"<i><tg-emoji emoji-id=\"{EMOJI_ID_INFO}\">❕</tg-emoji> В беседе команды работают при упоминании бота или ответе на его сообщение.</i>\n"
        f"<i><tg-emoji emoji-id=\"{EMOJI_ID_IDEA}\">💡</tg-emoji> В ЛС команды доступны владельцу и пользователям из списка группы.</i>\n"
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

async def handle_unsubscribe_command(message: Message, normalized_text: str) -> bool:
    if normalized_text != "отписаться":
        return False

    user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
    in_group = message.chat.type in ("group", "supergroup")
    tag_unsub = "GR" if in_group else "PM"
    if in_group:
        _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): запрос 'отписаться' в группе — отклонено")
        deny_text = f"<tg-emoji emoji-id=\"{EMOJI_ID_CROSS}\">❌</tg-emoji> Эта команда доступна только в личных сообщениях с ботом."
        try:
            await message.answer(deny_text, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer("❌ Эта команда доступна только в личных сообщениях с ботом.", parse_mode="HTML")
        return True
    else:
        _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): запрос 'отписаться'")

    user = next((u for u in birthday_service.users if u.user_id == message.from_user.id), None)
    if user:
        if user.interacted_with_bot:
            user.interacted_with_bot = False
            _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): успешная отписка от поздравлений")
            birthday_service.save_users()
            success_text = (
                f"<tg-emoji emoji-id=\"{EMOJI_ID_CHECK}\">✅</tg-emoji> Вы отписались от поздравлений.\n\n"
                "Чтобы снова получать поздравления, напишите боту любое сообщение."
            )
            await message.answer(success_text, parse_mode="HTML")
        else:
            _log(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): повторная отписка от поздравлений")
            info_text = (
                f"<tg-emoji emoji-id=\"{EMOJI_ID_INFO_ALT}\">ℹ️</tg-emoji> Вы и так не подписаны на поздравления.\n\n"
                "Чтобы получать поздравления, напишите боту любое сообщение."
            )
            await message.answer(info_text, parse_mode="HTML")
    else:
        _log(f"{tag_unsub}; Бот: пользователь {user_login_log or message.from_user.id} не найден в списке пользователей")
        not_found_text = f"<tg-emoji emoji-id=\"{EMOJI_ID_CROSS}\">❌</tg-emoji> Вы не найдены в списке пользователей."
        try:
            await message.answer(not_found_text, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer("❌ Вы не найдены в списке пользователей.", parse_mode="HTML")
    return True

async def handle_owner_commands(message: Message, normalized_text: str) -> bool:
    if normalized_text not in OWNER_COMMANDS:
        return False

    if message.from_user.id != OWNER_CHAT_ID:
        user_login = f"@{message.from_user.username}" if message.from_user.username else ""
        if message.chat.type in ("group", "supergroup"):
            _log(f"GR; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
        else:
            _log(f"PM; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
        deny_text = f"<tg-emoji emoji-id=\"{EMOJI_ID_CROSS}\">❌</tg-emoji> <b>В доступе отказано</b>\n\nЭта команда доступна только владельцу бота."
        try:
            await message.answer(deny_text, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer("❌ <b>В доступе отказано</b>\n\nЭта команда доступна только владельцу бота.", parse_mode="HTML")
        return True

    if await handle_owner_command(message):
        return True
    return True

async def handle_public_commands(message: Message, ctx: dict) -> bool:
    normalized_text = ctx["normalized_text"]
    text_for_commands = ctx["text_for_commands"]
    is_group_chat = ctx["is_group_chat"]

    if ctx["is_private_non_owner"] and not ctx["is_whitelisted_private"] and is_public_command(normalized_text):
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        _log(
            f"PM; От {user_login_log} ({message.from_user.full_name}): попытка команды '{normalized_text}' — отклонено (нет в списке)"
        )
        deny_text = f"<tg-emoji emoji-id=\"{EMOJI_ID_CROSS}\">❌</tg-emoji> <b>Эта команда доступна только избранным пользователям.</b>"
        try:
            await message.answer(deny_text, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer("❌ <b>Эта команда доступна только избранным пользователям.</b>", parse_mode="HTML")
        return True

    if normalized_text == "др" and ctx["should_process_birthday_command"]:
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if is_group_chat else "PM"
        _log(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др'")

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
        title = (
            f"<tg-emoji emoji-id=\"{EMOJI_ID_BOOKS}\">📚</tg-emoji> Пары на завтра:"
            if day_label == "завтра"
            else f"<tg-emoji emoji-id=\"{EMOJI_ID_BOOKS}\">📚</tg-emoji> Пары на сегодня:"
        )
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
            text = schedule_service.format_classes(
                events,
                f"<tg-emoji emoji-id=\"{EMOJI_ID_BOOKS}\">📚</tg-emoji> Пары на завтра:",
                empty_text,
                wrap_quote=True,
            )
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
