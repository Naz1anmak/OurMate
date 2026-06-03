"""Апдейты участников беседы.

Сейчас: чистка пинг-листа при выходе/исключении. Спроектировано как общая точка
входа — позже сюда добавится ветка прибытия (приветствие новеньких).
"""
import logging

from aiogram import F
from aiogram.types import ChatMemberUpdated, Message

from src.bot.services.ping_store import ping_store

logger = logging.getLogger(__name__)

_GONE_STATUSES = {"left", "kicked"}


async def on_chat_member_update(event: ChatMemberUpdated) -> None:
    """ChatMemberUpdated (бот — админ). Выход/исключение → убрать из пинг-листа."""
    new = event.new_chat_member
    if new is None or new.user is None:
        return
    if new.status in _GONE_STATUSES:
        await ping_store.leave(event.chat.id, new.user.id)
        logger.info("ping: убрал user_id=%s из chat_id=%s (статус %s)",
                    new.user.id, event.chat.id, new.status)
    # Точка расширения: ветка прибытия (status -> member) для будущего приветствия.


async def on_left_chat_member(message: Message) -> None:
    """Бэкап для обычных групп: сервисное сообщение о выходе участника."""
    left = message.left_chat_member
    if left is None:
        return
    await ping_store.leave(message.chat.id, left.id)
    logger.info("ping: убрал user_id=%s из chat_id=%s (left_chat_member)",
                left.id, message.chat.id)


def register_chat_member_handlers(dp) -> None:
    """Регистрируется ДО catch-all on_mention_or_reply (порядок важен для message-хендлера)."""
    dp.chat_member.register(on_chat_member_update)
    dp.message.register(on_left_chat_member, F.left_chat_member)
