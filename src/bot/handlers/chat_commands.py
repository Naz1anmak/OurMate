"""Обработчики команд для чата (общие для PM и групп)."""
import logging
from datetime import datetime, date
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from src.config.settings import OWNER_CHAT_ID, TIMEZONE
from src.bot.services.birthday_service import birthday_service
from src.bot.services.schedule_service import schedule_service
from src.utils.date_utils import format_birthday_date
from src.bot.handlers.owner_commands import handle_owner_command, OWNER_COMMANDS
from src.bot.handlers.chat_context import is_public_command

logger = logging.getLogger(__name__)


async def handle_help_command(message: Message, normalized_text: str) -> bool:
    help_commands = {"help", "команды"}
    if normalized_text not in help_commands:
        return False

    user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
    tag = "GR" if message.chat.type in ("group", "supergroup") else "PM"
    logger.info("%s; От %s (%s): запрос '%s'", tag, user_login_log, message.from_user.full_name, normalized_text)

    base_help = (
        "<b>Доступные команды:</b>\n\n"
        "• <code>др</code> — ближайший день рождения\n"
        "• <code>др &lt;id&gt;</code> или <code>др @username</code> — дата дня рождения по id или username\n"
        "• <code>пары</code> — пары на сегодня\n"
        "• <code>пары завтра</code> — пары на завтра\n"
        "• <code>отписаться</code> — отключить поздравления (в ЛС с ботом)\n"
        "• <code>help</code> или <code>команды</code> — справка по командам\n\n"
        f"<i>❕ В беседе команды работают при упоминании бота или ответе на его сообщение.</i>\n"
        f"<i>💡 В ЛС команды доступны владельцу и пользователям из списка группы.</i>\n"
    )

    if message.from_user.id == OWNER_CHAT_ID:
        admin_block = (
            "\n<b>Админские команды:</b>\n"
            "• <code>logs</code> — логи бота\n"
            "• <code>full logs</code> — полные логи\n"
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
        logger.info("%s; От %s (%s): запрос 'отписаться' в группе — отклонено", tag_unsub, user_login_log, message.from_user.full_name)
        deny_text = f"❌ Эта команда доступна только в личных сообщениях с ботом."
        try:
            await message.answer(deny_text, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer("❌ Эта команда доступна только в личных сообщениях с ботом.", parse_mode="HTML")
        return True
    else:
        logger.info(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): запрос 'отписаться'")

    user = next((u for u in birthday_service.users if u.user_id == message.from_user.id), None)
    if user:
        if user.interacted_with_bot:
            user.interacted_with_bot = False
            logger.info(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): успешная отписка от поздравлений")
            birthday_service.save_users()
            success_text = (
                f"✅ Вы отписались от поздравлений.\n\n"
                "Чтобы снова получать поздравления, напишите боту любое сообщение."
            )
            await message.answer(success_text, parse_mode="HTML")
        else:
            logger.info(f"{tag_unsub}; От {user_login_log} ({message.from_user.full_name}): повторная отписка от поздравлений")
            info_text = (
                f"ℹ️ Вы и так не подписаны на поздравления.\n\n"
                "Чтобы получать поздравления, напишите боту любое сообщение."
            )
            await message.answer(info_text, parse_mode="HTML")
    else:
        logger.info(f"{tag_unsub}; Бот: пользователь {user_login_log or message.from_user.id} не найден в списке пользователей")
        not_found_text = f"❌ Вы не найдены в списке пользователей."
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
            logger.info(f"GR; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
        else:
            logger.info(f"PM; От {user_login} ({message.from_user.full_name}): попытка команды '{message.text}' — отказано")
        deny_text = f"❌ <b>В доступе отказано</b>\n\nЭта команда доступна только владельцу бота."
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
        logger.info(
            f"PM; От {user_login_log} ({message.from_user.full_name}): попытка команды '{normalized_text}' — отклонено (нет в списке)"
        )
        deny_text = f"❌ <b>Эта команда доступна только избранным пользователям.</b>"
        try:
            await message.answer(deny_text, parse_mode="HTML")
        except TelegramBadRequest:
            await message.answer("❌ <b>Эта команда доступна только избранным пользователям.</b>", parse_mode="HTML")
        return True

    if normalized_text == "др" and ctx["should_process_birthday_command"]:
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if is_group_chat else "PM"
        logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др'")

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
                logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др' без аргумента")
                await message.answer("Укажи user_id или @username (др 123456 или др @user). Команда срабатывает по упоминанию бота или ответу на его сообщение.")
                return True
            found_user = next(
                (u for u in birthday_service.users if u.username and u.username.lower() == lookup.lower()),
                None,
            )
            logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др @{lookup}'")
        else:
            found_user = next((u for u in birthday_service.users if u.user_id == target_id), None)
            logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'др {target_id}'")

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
            logger.info(
                f"{tag}; Бот: пользователь не найден в списке дней рождения по запросу '{search_value}' (запрос от {user_login_log} ({message.from_user.full_name}))"
            )
            await message.answer("Пользователь не найден в списке дней рождения.")
        return True

    if normalized_text == "пары" and ctx["should_process_schedule_command"]:
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if ctx["is_group_chat"] else "PM"
        logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'пары'")
        effective_date = schedule_service.get_effective_date(TIMEZONE)
        events = schedule_service.get_classes_for_date(effective_date)
        today = datetime.now(TIMEZONE).date()
        day_label = "завтра" if effective_date == date.fromordinal(today.toordinal() + 1) else "сегодня"
        base_title = "Пары на завтра" if day_label == "завтра" else "Пары на сегодня"
        empty_text = schedule_service.get_no_pairs_message(day_label)
        if events:
            text = schedule_service.format_day_block(effective_date, base_title, icon_common="📚")
        else:
            next_date, next_events = schedule_service.get_next_classes_after(effective_date)
            if next_date and next_events:
                next_block = schedule_service.format_next_classes_block(next_date, base_date=effective_date)
                text = f"{empty_text}\n\n{next_block}"
            else:
                text = empty_text
        await message.answer(text, parse_mode="HTML")
        return True

    if normalized_text == "пары завтра" and ctx["should_process_schedule_command"]:
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if ctx["is_group_chat"] else "PM"
        logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'пары завтра'")
        tomorrow = date.fromordinal(datetime.now(TIMEZONE).date().toordinal() + 1)
        events = schedule_service.get_classes_for_date(tomorrow)
        empty_text = schedule_service.get_no_pairs_message("завтра")
        if events:
            text = schedule_service.format_day_block(tomorrow, "Пары на завтра", icon_common="📚")
        else:
            next_date, next_events = schedule_service.get_next_classes_after(tomorrow)
            if next_date and next_events:
                next_block = schedule_service.format_next_classes_block(next_date, base_date=tomorrow)
                text = f"{empty_text}\n\n{next_block}"
            else:
                text = empty_text
        await message.answer(text, parse_mode="HTML")
        return True

    return False
