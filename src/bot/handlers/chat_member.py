"""Апдейты участников беседы.

Выход/исключение — чистка пинг-листа и списков. Прибытие — приветствие новенького.
"""
import logging

from aiogram import F
from aiogram.types import ChatMemberUpdated, Message

from src.bot.services.ping_store import ping_store
from src.bot.services.notes_store import notes_store
from src.bot.services.welcome import welcome_member

logger = logging.getLogger(__name__)

_GONE_STATUSES = {"left", "kicked"}
# Из этих статусов переход в member/restricted означает именно приход, а не смену прав.
_OUTSIDE_STATUSES = {"left", "kicked", None}
_INSIDE_STATUSES = {"member", "restricted"}


async def on_chat_member_update(event: ChatMemberUpdated) -> None:
    """ChatMemberUpdated (бот — админ). Выход/исключение → убрать из пинг-листа."""
    new = event.new_chat_member
    if new is None or new.user is None:
        return
    if new.status in _GONE_STATUSES:
        await ping_store.leave(event.chat.id, new.user.id)
        logger.info("ping: убрал user_id=%s из chat_id=%s (статус %s)",
                    new.user.id, event.chat.id, new.status)
        removed = await notes_store.remove_member_everywhere(event.chat.id, new.user.id)
        if removed:
            logger.info("notes: убрал user_id=%s из %d списков chat_id=%s",
                        new.user.id, removed, event.chat.id)
    elif new.status in _INSIDE_STATUSES:
        old = event.old_chat_member
        old_status = old.status if old is not None else None
        # Повышение до админа и обратно тоже прилетает сюда — приветствуем только приход извне.
        if old_status in _OUTSIDE_STATUSES:
            await welcome_member(event.bot, event.chat.id, new.user)


async def on_left_chat_member(message: Message) -> None:
    """Бэкап для обычных групп: сервисное сообщение о выходе участника."""
    left = message.left_chat_member
    if left is None:
        return
    await ping_store.leave(message.chat.id, left.id)
    logger.info("ping: убрал user_id=%s из chat_id=%s (left_chat_member)",
                left.id, message.chat.id)
    await notes_store.remove_member_everywhere(message.chat.id, left.id)


async def on_new_chat_members(message: Message) -> None:
    """Бэкап для обычных групп: сервисное сообщение о входе участников."""
    for user in message.new_chat_members or []:
        await welcome_member(message.bot, message.chat.id, user)


def register_chat_member_handlers(dp) -> None:
    """Регистрируется ДО catch-all on_mention_or_reply (порядок важен для message-хендлеров)."""
    dp.chat_member.register(on_chat_member_update)
    dp.message.register(on_left_chat_member, F.left_chat_member)
    dp.message.register(on_new_chat_members, F.new_chat_members)
