"""Callback'и напоминаний: подписка-toggle и подтверждения create/update/cancel."""
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import CallbackQuery

from src.config.settings import TIMEZONE, OWNER_CHAT_ID
from src.bot.services.reminder_store import reminder_store
from src.bot.services import reminder_service as rs
from src.core.emoji import E

logger = logging.getLogger(__name__)

# Инжектится из main.py при старте (как tool_registry).
scheduler = None  # type: ignore


async def on_reminder_callback(query: CallbackQuery) -> None:
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "rem":
        await query.answer()
        return
    _, action, rid_s = parts
    reminder_id = int(rid_s)
    rem = await reminder_store.get(reminder_id)
    if not rem:
        await query.answer("Напоминание не найдено", show_alert=False)
        return

    user_id = query.from_user.id
    is_owner = user_id == OWNER_CHAT_ID
    now = datetime.now(TIMEZONE)

    if action == "sub":
        await _toggle_subscription(query, rem, now)
        return

    # Остальные действия — только автор/владелец.
    if not rs.can_modify(rem, user_id=user_id, is_owner=is_owner):
        await query.answer("Только автор может это сделать", show_alert=True)
        return

    if action == "ok":      # подтвердить черновик (ЛС)
        await reminder_store.set_status(reminder_id, "pending")
        scheduler.schedule(reminder_id, rem["fire_at"])
        await query.message.edit_text(rs.render_confirm_pm(rem, now) + f"\n\n{E.CHECK} Создано",
                                      parse_mode="HTML")
        await query.answer("Готово")
    elif action == "no":    # отменить черновик
        await reminder_store.set_status(reminder_id, "cancelled")
        await query.message.edit_text(f"{E.CROSS} Отменено")
        await query.answer()
    elif action == "upd":   # применить отложенную правку
        await reminder_store.apply_pending_update(reminder_id)
        # Правка может прийти на черновик (ЛС, ещё не подтверждён): подтверждение
        # правки заодно активирует напоминание, иначе job выстрелит вхолостую (_fire
        # пропускает не-pending).
        if rem["status"] == "draft":
            await reminder_store.set_status(reminder_id, "pending")
        fresh = await reminder_store.get(reminder_id)
        scheduler.schedule(reminder_id, fresh["fire_at"])
        await _refresh_card(query.bot, fresh, now)
        await query.message.edit_text(f"{E.CHECK} Обновлено")
        await query.answer("Обновлено")
    elif action == "undo":  # отказаться от правки
        await reminder_store.clear_pending_update(reminder_id)
        await query.message.edit_text("Оставил как было")
        await query.answer()
    elif action == "del":   # подтвердить отмену
        await reminder_store.set_status(reminder_id, "cancelled")
        scheduler.unschedule(reminder_id)
        await query.message.edit_text(f"{E.CROSS} Напоминание отменено")
        await query.answer("Отменено")
    elif action == "keep":  # передумал отменять
        await query.message.edit_text("Оставил напоминание")
        await query.answer()
    else:
        await query.answer()


async def _toggle_subscription(query: CallbackQuery, rem: dict, now: datetime) -> None:
    u = query.from_user
    subscribed = await reminder_store.toggle_subscriber(
        rem["id"], user_id=u.id, first_name=u.first_name, username=u.username)
    count = await reminder_store.count_subscribers(rem["id"])
    try:
        await query.message.edit_text(
            rs.render_card(rem, count, now), parse_mode="HTML",
            reply_markup=rs.card_keyboard(rem["id"], subscribed))
    except Exception as exc:  # noqa: BLE001 — текст не изменился / карточка устарела
        logger.debug("edit карточки не удался: %s", exc)
    await query.answer("Напомню тебе" if subscribed else "Отписал")


async def _refresh_card(bot: Bot, rem: dict, now: datetime) -> None:
    """Перерисовать публичную карточку после правки (если она есть)."""
    if rem["scope"] != "chat" or not rem["card_message_id"]:
        return
    count = await reminder_store.count_subscribers(rem["id"])
    try:
        await bot.edit_message_text(
            rs.render_card(rem, count, now), chat_id=rem["chat_id"],
            message_id=rem["card_message_id"], parse_mode="HTML",
            reply_markup=rs.card_keyboard(rem["id"], False))
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh карточки не удался: %s", exc)
