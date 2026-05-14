"""
Обработчики команд бота.
Содержит функции для обработки команд типа /start, /help и т.д.
"""
import logging

from aiogram import types
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest
from aiogram.filters import Command

from src.bot.services.birthday_service import birthday_service

logger = logging.getLogger(__name__)

async def cmd_start(message: types.Message):
    """
    Обработчик команды /start.
    Отправляет приветственное сообщение пользователю.
    
    Args:
        message (types.Message): Сообщение с командой
    """
    # Логируем информацию о пользователе
    user_login = f"@{message.from_user.username}" if message.from_user.username else ""
    user_name = message.from_user.full_name or str(message.from_user.id)
    if user_login:
        logger.info(f"FP; От {user_login} ({user_name}): /start")
    else:
        logger.info(f"FP; От {user_name}: /start")
    
    # Отмечаем пользователя активировавшим бота, если он есть в списке
    from src.config.settings import OWNER_CHAT_ID
    user_record = next((u for u in birthday_service.users if u.user_id == message.from_user.id), None)
    if user_record and not user_record.interacted_with_bot:
        user_record.interacted_with_bot = True
        birthday_service.save_users()

    # Уведомляем владельца о новом /start (кроме его собственного)
    if message.from_user.id != OWNER_CHAT_ID:
        try:
            await message.bot.send_message(
                OWNER_CHAT_ID,
                (
                    f"📲 Новый /start\n"
                    f"От: {message.from_user.full_name} {user_login}\n"
                    f"user_id: {message.from_user.id}"
                ),
                parse_mode="HTML",
            )
        except TelegramNetworkError as exc:
            logger.warning(f"PM; Бот: не удалось уведомить владельца о /start: {exc}")
        except Exception as exc:
            logger.warning(f"PM; Бот: неожиданная ошибка при уведомлении владельца о /start: {exc}")

    # Проверяем, является ли пользователь владельцем
    if message.from_user.id == OWNER_CHAT_ID:
        welcome_text = (
            f"🤖 <b>Привет, владелец!</b>\n\n"
            "Я бот с подключенной нейросетью. Помимо обычного чата, у вас есть доступ к специальным командам:\n\n"
            "<b>Команды управления:</b>\n"
            "• <code>logs</code> — Логи бота\n"
            "• <code>full logs</code> — Полные логи\n"
            "• <code>проверка ссылок</code> — Диагностика ссылок/активации\n"
            "• <code>help</code> или <code>команды</code> — Справка по командам\n\n"
            "<b>Команды по дням рождения:</b>\n"
            "• <code>др</code> — Ближайший день рождения\n"
            "• <code>др &lt;user_id&gt;</code> или <code>др @username</code> — Дата рождения по id или username\n\n"
            "<b>Команды по расписанию:</b>\n"
            "• <code>пары</code> — Пары на сегодня (в группе, при упоминании бота)\n"
            "• <code>пары завтра</code> — Пары на завтра (в группе, при упоминании бота)\n\n"
            "<b>Управление подпиской:</b>\n"
            "• <code>отписаться</code> — Отключить поздравления (в ЛС с ботом)\n\n"
            "<b>Обычный чат:</b>\n"
            "Просто напишите мне сообщение, и я отвечу с помощью нейросети."
        )
    else:
        welcome_text = (
            f"🤖 <b>Привет!</b>\n\n"
            "Я бот с подключенной нейросетью. Чтобы задать мне вопрос — просто напиши его тут, а в группе упомяни меня через @ или ответь на моё сообщение.\n\n"
            f"💬 Я запоминаю контекст наших диалогов, поэтому могу поддерживать осмысленную беседу.\n\n"
            "<b>Команды по дням рождения:</b>\n"
            "• <code>др</code> — Ближайший день рождения\n"
            "• <code>др &lt;id&gt;</code> или <code>др @username</code> — Дата дня рождения пользователя по id или username\n\n"
            "<b>Команды по расписанию:</b>\n"
            "• <code>пары</code> — Пары на сегодня\n"
            "• <code>пары завтра</code> — Пары на завтра\n\n"
            "<b>Управление подпиской:</b>\n"
            "• <code>отписаться</code> — Отключить поздравления\n\n"
            "<b>Справка:</b>\n"
            "• <code>help</code> или <code>команды</code>\n\n"
            f"<i>❕ В беседе нужно упомянуть бота или ответить на его сообщение.</i>\n\n"
            "<b>Команды управления (для владельца):</b>\n"
            "• <code>logs</code> — Логи бота\n"
            "• <code>full logs</code> — Полные логи\n"
            "• <code>проверка ссылок</code> — Диагностика ссылок/активации\n\n"
            "<b>Хотите больше функций?</b>\n"
            "Вы можете клонировать этого бота для своей беседы и настроить под себя:\n\n"
            f"🔗 <a href=\"https://github.com/Naz1anmak/OurMate\">GitHub репозиторий</a>"
        )

    try:
        await message.answer(welcome_text, parse_mode="HTML")
    except TelegramBadRequest as exc:
        logger.warning(
            f"PM; Бот: ошибка отправки приветствия для {user_login or message.from_user.id}: {exc}"
        )
    except TelegramNetworkError as exc:
        logger.warning(
            f"PM; Бот: ошибка отправки приветствия для {user_login or message.from_user.id}: {exc}"
        )
    except Exception as exc:
        logger.warning(
            f"PM; Бот: неожиданная ошибка при отправке приветствия для {user_login or message.from_user.id}: {exc}"
        )

def register_command_handlers(dp):
    """
    Регистрирует обработчики команд в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(cmd_start, Command("start"))
