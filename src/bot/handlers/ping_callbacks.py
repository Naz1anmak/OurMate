"""Колбэки пинг-панели: вступление/выход + обновление счётчика на той же панели."""
import logging

from aiogram.types import CallbackQuery

from src.bot.services.ping_store import ping_store
from src.bot.services import ping_service

logger = logging.getLogger(__name__)


async def on_ping_callback(query: CallbackQuery) -> None:
    parts = (query.data or "").split(":")
    if len(parts) != 2 or parts[0] != "ping" or query.message is None:
        await query.answer()
        return
    action = parts[1]
    chat_id = query.message.chat.id
    user = query.from_user
    who = f"@{user.username}" if user.username else (user.first_name or str(user.id))

    if action == "join":
        await ping_store.join(
            chat_id=chat_id, user_id=user.id,
            first_name=user.first_name, username=user.username,
        )
        toast = "Вы в списке — теперь вас позовут по @all"
    elif action == "leave":
        removed = await ping_store.leave(chat_id, user.id)
        toast = "Вы вышли из списка" if removed else "Вас и не было в списке"
    else:
        await query.answer()
        return

    count = await ping_store.count(chat_id)
    logger.info("GR; От %s: пинг-лист '%s' (в списке: %d)", who, action, count)
    try:
        await query.message.edit_text(
            ping_service.panel_text(count),
            reply_markup=ping_service.panel_keyboard(),
            parse_mode="HTML",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("ping: edit панели не удался: %s", exc)
    await query.answer(toast, show_alert=False)
