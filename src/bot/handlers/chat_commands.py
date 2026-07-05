"""Обработчики команд для чата (общие для PM и групп)."""
import logging
from datetime import datetime, date, timedelta
from typing import TYPE_CHECKING
from aiogram.types import Message
from src.config.settings import OWNER_CHAT_ID, TIMEZONE
from src.bot.services.birthday_service import birthday_service
from src.bot.services.schedule_service import schedule_service
from src.bot.services.reminder_store import reminder_store
from src.bot.services import reminder_service as rs
from src.utils.date_utils import format_birthday_date
from src.core.emoji import E
from src.bot.services.ping_store import ping_store
from src.bot.services import ping_service
from src.bot.services.notes_store import notes_store
from src.bot.services import notes_service

if TYPE_CHECKING:
    from src.bot.services.schedule_refresher import ScheduleRefresher

# инжектятся из setup.py в Task 17
schedule_refresher: "ScheduleRefresher | None" = None
pinned_scheduler = None  # PinnedScheduleScheduler | None

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
        "• <code>обнови расписание</code> — обновить расписание и закреп\n"
        "• <code>пинг</code> — список для уведомлений (вступить/выйти кнопками)\n"
        "• <code>@all</code> — позвать всех из списка (в беседе, без упоминания бота)\n"
        "• <code>отписаться</code> — отключить поздравления (в ЛС с ботом)\n"
        "• <code>help</code> или <code>команды</code> — справка по командам\n\n"
        f"<i>{E.INFO} В беседе команды работают при упоминании бота или ответе на его сообщение.</i>\n"
        f"<i>{E.IDEA} В ЛС команды доступны владельцу и пользователям из списка группы.</i>\n"
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
    logger.info(f"PM; От {user_login_log} ({message.from_user.full_name}): запрос 'отписаться'")

    user = next((u for u in birthday_service.users if u.user_id == message.from_user.id), None)
    if user:
        if user.subscribed:
            user.subscribed = False
            logger.info(f"PM; От {user_login_log} ({message.from_user.full_name}): успешная отписка от поздравлений")
            birthday_service.save_users()
            success_text = (
                f"{E.CHECK} Вы отписались от поздравлений.\n\n"
                "Чтобы снова получать поздравления, напишите боту любое сообщение."
            )
            await message.answer(success_text, parse_mode="HTML")
        else:
            logger.info(f"PM; От {user_login_log} ({message.from_user.full_name}): повторная отписка от поздравлений")
            info_text = (
                f"{E.INFO_ALT} Вы и так не подписаны на поздравления.\n\n"
                "Чтобы получать поздравления, напишите боту любое сообщение."
            )
            await message.answer(info_text, parse_mode="HTML")
    else:
        logger.info(f"PM; Бот: пользователь {user_login_log or message.from_user.id} не найден в списке пользователей")
        not_found_text = f"{E.CROSS} Вы не найдены в списке пользователей."
        await message.answer(not_found_text, parse_mode="HTML")
    return True

async def handle_public_commands(message: Message, ctx: dict) -> bool:
    normalized_text = ctx["normalized_text"]
    text_for_commands = ctx["text_for_commands"]
    is_group_chat = ctx["is_group_chat"]

    if normalized_text == "др":
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

    if normalized_text.startswith("др "):
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

    if normalized_text == "пары":
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if ctx["is_group_chat"] else "PM"
        logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'пары'")
        refresh_result = None
        if schedule_refresher is not None and ctx["is_group_chat"]:
            try:
                refresh_result = await schedule_refresher.ensure_fresh("cmd:пары")
            except Exception as exc:  # noqa: BLE001
                logger.warning("ensure_fresh из 'пары' упал: %s", exc)
        effective_date, day_label, base_title = schedule_service.get_effective_date_with_titles(TIMEZONE)
        events = schedule_service.get_classes_for_date(effective_date)
        empty_text = schedule_service.get_no_pairs_message(day_label)
        if events:
            text = schedule_service.format_day_block(effective_date, base_title, icon_common=str(E.NO_CLASS_BOOKS))
        else:
            next_date, next_events = schedule_service.get_next_classes_after(effective_date)
            if next_date and next_events:
                next_block = schedule_service.format_next_classes_block(next_date)
                text = f"{empty_text}\n\n{next_block}"
            else:
                text = empty_text
        await message.answer(text, parse_mode="HTML")
        if refresh_result is not None and getattr(refresh_result, "diff_message", None):
            try:
                await message.answer(refresh_result.diff_message, parse_mode="HTML")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Не удалось отправить diff после 'пары': %s", exc)
        return True

    if normalized_text == "пары завтра":
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if ctx["is_group_chat"] else "PM"
        logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'пары завтра'")
        refresh_result = None
        if schedule_refresher is not None and ctx["is_group_chat"]:
            try:
                refresh_result = await schedule_refresher.ensure_fresh("cmd:пары завтра")
            except Exception as exc:  # noqa: BLE001
                logger.warning("ensure_fresh из 'пары завтра' упал: %s", exc)
        tomorrow = date.fromordinal(datetime.now(TIMEZONE).date().toordinal() + 1)
        events = schedule_service.get_classes_for_date(tomorrow)
        empty_text = schedule_service.get_no_pairs_message("завтра")
        if events:
            text = schedule_service.format_day_block(tomorrow, "Пары на завтра", icon_common=str(E.NO_CLASS_BOOKS))
        else:
            next_date, next_events = schedule_service.get_next_classes_after(tomorrow)
            if next_date and next_events:
                next_block = schedule_service.format_next_classes_block(next_date)
                text = f"{empty_text}\n\n{next_block}"
            else:
                text = empty_text
        await message.answer(text, parse_mode="HTML")
        if refresh_result is not None and getattr(refresh_result, "diff_message", None):
            try:
                await message.answer(refresh_result.diff_message, parse_mode="HTML")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Не удалось отправить diff после 'пары завтра': %s", exc)
        return True

    if normalized_text == "обнови расписание":
        user_login_log = f"@{message.from_user.username}" if message.from_user.username else ""
        tag = "GR" if ctx["is_group_chat"] else "PM"
        logger.info(f"{tag}; От {user_login_log} ({message.from_user.full_name}): запрос 'обнови расписание'")

        reply = await message.answer("⌛ <i>Обновляю расписание…</i>", parse_mode="HTML")
        if schedule_refresher is None:
            await message.bot.edit_message_text(
                "⚠️ Автообновление расписания не настроено.",
                chat_id=message.chat.id, message_id=reply.message_id, parse_mode="HTML",
            )
            return True

        try:
            result = await schedule_refresher.force_refresh("cmd:обнови расписание")
        except Exception as exc:  # noqa: BLE001
            logger.warning("force_refresh из команды упал: %s", exc)
            result = None

        if result is None or (not result.updated_groups and result.failed_groups):
            # полный провал
            from src.bot.services.schedule_parser import load_schedule
            link_code = sorted(schedule_refresher.group_ids.keys())[0] if schedule_refresher.group_ids else None
            link = "—"
            stamp = "—"
            if link_code:
                today = datetime.now(TIMEZONE).date()
                monday = today - timedelta(days=today.weekday())
                link = schedule_refresher.client.public_url(schedule_refresher.group_ids[link_code], monday)
                fetched, _events = load_schedule(link_code)
                if fetched:
                    stamp = fetched.strftime("%d.%m %H:%M")
            text = (
                f"⚠️ <a href=\"{link}\">Расписание</a> недоступно, "
                f"остался прошлый снимок (от {stamp})."
            )
            await message.bot.edit_message_text(
                text, chat_id=message.chat.id, message_id=reply.message_id,
                parse_mode="HTML", disable_web_page_preview=True,
            )
            return True

        text_parts: list[str] = []
        if result.diff_message:
            text_parts.append(result.diff_message)
        else:
            text_parts.append("✅ Готово, расписание не изменилось.")
        if result.failed_groups:
            text_parts.append(f"❗️ Не удалось обновить: {', '.join(result.failed_groups)}")

        await message.bot.edit_message_text(
            "\n\n".join(text_parts),
            chat_id=message.chat.id, message_id=reply.message_id,
            parse_mode="HTML", disable_web_page_preview=True,
        )

        if pinned_scheduler is not None:
            try:
                await pinned_scheduler.update_now()
            except Exception as exc:  # noqa: BLE001
                logger.warning("pinned.update_now после команды упал: %s", exc)
        return True

    return False


async def handle_reminders_command(message: Message) -> bool:
    """Слово-команда «напоминания»: детерминированный список (в группе — беседы, в ЛС — личные)."""
    now = datetime.now(TIMEZONE)
    is_group = message.chat.type in ("group", "supergroup")
    if is_group:
        items = await reminder_store.list_pending_for_chat(message.chat.id)
        header = "Напоминания беседы"
    else:
        items = await reminder_store.list_pending_for_author(message.from_user.id)
        header = "Твои напоминания"
    await message.answer(rs.render_list(items, header=header, now=now),
                         parse_mode="HTML", disable_web_page_preview=True)
    return True


async def handle_lists_command(message: Message) -> None:
    """Слово-команда «списки»: детерминированный обзор списков беседы (только основная беседа)."""
    chat_id = message.chat.id
    notes = await notes_store.list_for_chat(chat_id)
    logger.info("GR; От %s: команда 'списки' (%d шт.)", _user_log_id(message), len(notes))
    await message.answer(notes_service.render_overview(notes), parse_mode="HTML")


def _user_log_id(message: Message) -> str:
    """Логин/имя автора для логов в стиле проекта."""
    u = message.from_user
    if u and u.username:
        return f"@{u.username}"
    return (u.full_name if u else None) or str(u.id if u else "?")


async def handle_ping_command(message: Message) -> None:
    """Команда `пинг`: панель со счётчиком и кнопками вступления/выхода. Никого не зовёт."""
    count = await ping_store.count(message.chat.id)
    logger.info("GR; От %s: команда 'пинг' (в списке: %d)", _user_log_id(message), count)
    await message.answer(
        ping_service.panel_text(count),
        reply_markup=ping_service.panel_keyboard(),
        parse_mode="HTML",
    )


async def handle_ping_all(message: Message) -> None:
    """Триггер `@all`: пинг всех участников пинг-листа этой беседы (с кулдауном)."""
    chat_id = message.chat.id
    who = _user_log_id(message)
    members = await ping_store.list_members(chat_id)
    if not members:
        logger.info("GR; От %s: @all — список пуст", who)
        await message.answer(
            f"{E.REMINDER} Список пуст. Наберите <code>пинг</code>, чтобы вступить.",
            parse_mode="HTML",
        )
        return
    remaining = ping_service.cooldown_remaining(chat_id)
    if remaining > 0:
        mins = int(remaining // 60) + 1
        logger.info("GR; От %s: @all — кулдаун, осталось ~%d мин", who, mins)
        await message.answer(
            f"{E.THINK_HOURGLASS} Недавно уже звали. Подождите ~{mins} мин.",
            parse_mode="HTML",
        )
        return
    logger.info("GR; От %s: @all → пинг %d участникам", who, len(members))
    for text in ping_service.build_ping_messages(members):
        await message.answer(text, parse_mode="HTML")
    ping_service.mark_fired(chat_id)
