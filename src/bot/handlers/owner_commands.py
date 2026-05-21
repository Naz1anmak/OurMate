"""Обработчики команд владельца бота."""
import logging

from aiogram.types import Message

from src.config.settings import OWNER_CHAT_ID
from src.bot.services.system_service import system_service
from src.bot.services.birthday_service import birthday_service
from src.core.emoji import E

logger = logging.getLogger(__name__)


OWNER_COMMANDS = {
    "logs",
    "full logs",
    "проверка ссылок",
}


async def handle_owner_command(message: Message) -> bool:
    """Возвращает True, если команда обработана."""
    if message.from_user.id != OWNER_CHAT_ID:
        return False

    text = message.text.lower().strip()

    user_login = f"@{message.from_user.username}" if message.from_user.username else ""
    tag = "GR" if message.chat.type in ("group", "supergroup") else "PM"
    logger.info(f"{tag}; От {user_login} ({message.from_user.full_name}): запрос '{message.text}'")

    if text == "logs":
        await message.answer(system_service.get_bot_logs(), parse_mode="HTML")
        return True

    if text == "full logs":
        await message.answer(system_service.get_full_logs(), parse_mode="HTML")
        return True

    if text == "проверка ссылок":
        await message.answer(_render_links_check(), parse_mode="HTML", disable_web_page_preview=True)
        return True

    return False


def _render_links_check() -> str:
    """Диагностика гиперссылок и активации пользователей."""
    lines = ["🔍 <b>Проверка ссылок и активации:</b>\n"]
    for user in birthday_service.users:
        mention = user.mention_html()
        username_info = f" (@{user.username})" if user.username else ""

        if user.user_id is None:
            prefix = "⭕️"
        else:
            prefix = str(E.CHECK) if user.status == "active" else str(E.BAN)

        has_cake = user.user_id is not None and user.interacted_with_bot
        if has_cake:
            prefix = f"{prefix}🎂"
            lines.append(f"{prefix}{mention}{username_info}")
        else:
            lines.append(f"{prefix} — {mention}{username_info}")
    return "\n".join(lines)
