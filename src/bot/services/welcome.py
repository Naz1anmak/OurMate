"""Приветствие новых участников беседы.

Текст + гифка одним сообщением (гифка как animation с caption). `file_id`
первой успешной отправки кешируется в памяти — повторные приветствия не
перезагружают файл на серверы Telegram.
"""
from __future__ import annotations

import html
import logging
import time

from aiogram import Bot
from aiogram.types import FSInputFile, User

from src.config.settings import CHAT_ID, WELCOME_ENABLED, WELCOME_GIF_FILE
from src.core.emoji import E

logger = logging.getLogger(__name__)

# Кеш file_id гифки: живёт до перезапуска бота, при смене файла сбрасывается вместе с процессом.
_gif_file_id: str | None = None

# Защита от дубля: chat_member и сервисное new_chat_members могут прийти на одного человека.
_recent: dict[tuple[int, int], float] = {}
_DEDUP_TTL_SEC = 300.0


def _already_welcomed(chat_id: int, user_id: int) -> bool:
    """True, если этого участника уже приветствовали меньше `_DEDUP_TTL_SEC` назад."""
    now = time.monotonic()
    for key, ts in list(_recent.items()):
        if now - ts > _DEDUP_TTL_SEC:
            del _recent[key]
    key = (chat_id, user_id)
    if key in _recent:
        return True
    _recent[key] = now
    return False


def _caption(user: User) -> str:
    """«Добро пожаловать, <имя>!» — имя ссылкой на профиль, если id известен."""
    name = html.escape(user.first_name or user.full_name or "друг")
    mention = f'<a href="tg://user?id={user.id}">{name}</a>'
    return f"{E.WAVE} Добро пожаловать, {mention}!"


async def welcome_member(bot: Bot, chat_id: int, user: User) -> None:
    """Приветствует нового участника целевой беседы. Тихо выходит, если приветствие не нужно."""
    global _gif_file_id

    if not WELCOME_ENABLED:
        return
    if chat_id != CHAT_ID:
        return
    if user.is_bot:
        return
    if _already_welcomed(chat_id, user.id):
        logger.debug("welcome: user_id=%s уже приветствовали, пропуск", user.id)
        return

    caption = _caption(user)
    gif = WELCOME_GIF_FILE

    if _gif_file_id is None and not (gif and gif.is_file()):
        logger.warning("welcome: гифка %s не найдена, шлём только текст", gif)
        await bot.send_message(chat_id, caption, parse_mode="HTML")
        return

    media = _gif_file_id or FSInputFile(gif)
    try:
        message = await bot.send_animation(
            chat_id, animation=media, caption=caption, parse_mode="HTML"
        )
    except Exception as exc:  # noqa: BLE001
        # Устаревший file_id, битый файл, отобранное право на медиа — приветствие важнее гифки.
        logger.warning("welcome: гифка не отправилась (%s), шлём только текст", exc)
        _gif_file_id = None
        await bot.send_message(chat_id, caption, parse_mode="HTML")
        return

    if message.animation and _gif_file_id is None:
        _gif_file_id = message.animation.file_id
        logger.info("welcome: file_id гифки закеширован")
    logger.info("welcome: поприветствовали user_id=%s в chat_id=%s", user.id, chat_id)
