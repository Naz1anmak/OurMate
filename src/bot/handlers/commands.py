"""
Обработчики команд бота.
Содержит функции для обработки команд типа /start, /help и т.д.
"""
from aiogram import types
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest
from aiogram.filters import Command

from src.bot.services.birthday_service import birthday_service
from src.utils.log_utils import log_with_ts as _log

EMOJI_ID_ROBOT = "5372981976804366741"
EMOJI_ID_CHAT = "5443038326535759644"
EMOJI_ID_INFO = "5220197908342648622"
EMOJI_ID_LINK = "5375129357373165375"
EMOJI_ID_START = "5406809207947142040"

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
        _log(f"FP; От {user_login} ({user_name}): /start")
    else:
        _log(f"FP; От {user_name}: /start")
    
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
                    f"<tg-emoji emoji-id=\"{EMOJI_ID_START}\">📲</tg-emoji> Новый /start\n"
                    f"От: {message.from_user.full_name} {user_login}\n"
                    f"user_id: {message.from_user.id}"
                ),
                parse_mode="HTML",
            )
        except TelegramNetworkError as exc:
            _log(f"PM; Бот: не удалось уведомить владельца о /start: {exc}")
        except Exception as exc:
            _log(f"PM; Бот: неожиданная ошибка при уведомлении владельца о /start: {exc}")

    # Проверяем, является ли пользователь владельцем
    if message.from_user.id == OWNER_CHAT_ID:
        welcome_text = (
            f"<tg-emoji emoji-id=\"{EMOJI_ID_ROBOT}\">🤖</tg-emoji> <b>Привет, владелец!</b>\n\n"
            "Я бот с подключенной нейросетью. Помимо обычного чата, у вас есть доступ к специальным командам:\n\n"
            "<b>Команды управления:</b>\n"
            "• <code>logs</code> — Логи бота\n"
            "• <code>full logs</code> — Полные логи\n"
            "• <code>status</code> — Статус службы\n"
            "• <code>system</code> — Информация о системе\n"
            "• <code>stop bot</code> — Остановить бота\n"
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
            f"<tg-emoji emoji-id=\"{EMOJI_ID_ROBOT}\">🤖</tg-emoji> <b>Привет!</b>\n\n"
            "Я бот с подключенной нейросетью. Чтобы задать мне вопрос — просто напиши его тут, а в группе упомяни меня через @ или ответь на моё сообщение.\n\n"
            f"<tg-emoji emoji-id=\"{EMOJI_ID_CHAT}\">💬</tg-emoji> Я запоминаю контекст наших диалогов, поэтому могу поддерживать осмысленную беседу.\n\n"
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
            f"<i><tg-emoji emoji-id=\"{EMOJI_ID_INFO}\">❕</tg-emoji> В беседе нужно упомянуть бота или ответить на его сообщение.</i>\n\n"
            "<b>Команды управления (для владельца):</b>\n"
            "• <code>logs</code> — Логи бота\n"
            "• <code>full logs</code> — Полные логи\n"
            "• <code>status</code> — Статус службы\n"
            "• <code>system</code> — Информация о системе\n"
            "• <code>stop bot</code> — Остановить бота\n"
            "• <code>проверка ссылок</code> — Диагностика ссылок/активации\n\n"
            "<b>Хотите больше функций?</b>\n"
            "Вы можете клонировать этого бота для своей беседы и настроить под себя:\n\n"
            f"<tg-emoji emoji-id=\"{EMOJI_ID_LINK}\">🔗</tg-emoji> <a href=\"https://github.com/Naz1anmak/OurMate\">GitHub репозиторий</a>"
        )

    welcome_text_plain = (
        welcome_text
        .replace(f"<tg-emoji emoji-id=\"{EMOJI_ID_ROBOT}\">🤖</tg-emoji>", "🤖")
        .replace(f"<tg-emoji emoji-id=\"{EMOJI_ID_CHAT}\">💬</tg-emoji>", "💬")
        .replace(f"<tg-emoji emoji-id=\"{EMOJI_ID_INFO}\">❕</tg-emoji>", "❕")
        .replace(f"<tg-emoji emoji-id=\"{EMOJI_ID_LINK}\">🔗</tg-emoji>", "🔗")
    )

    try:
        await message.answer(welcome_text, parse_mode="HTML")
    except TelegramBadRequest as exc:
        try:
            await message.answer(welcome_text_plain, parse_mode="HTML")
        except Exception:
            _log(
                f"PM; Бот: ошибка отправки приветствия для {user_login or message.from_user.id}: {exc}"
            )
    except TelegramNetworkError as exc:
        _log(
            f"PM; Бот: ошибка отправки приветствия для {user_login or message.from_user.id}: {exc}"
        )
    except Exception as exc:
        _log(
            f"PM; Бот: неожиданная ошибка при отправке приветствия для {user_login or message.from_user.id}: {exc}"
        )

def register_command_handlers(dp):
    """
    Регистрирует обработчики команд в диспетчере.
    
    Args:
        dp: Диспетчер aiogram
    """
    dp.message.register(cmd_start, Command("start"))
