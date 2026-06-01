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


def _inactive_note(status: str) -> str:
    """Тост при клике по уже неактивному напоминанию."""
    if status == "fired":
        return "Это событие уже прошло"
    if status == "cancelled":
        return "Напоминание отменено"
    return "Событие неактивно — создай заново"


async def _safe_edit(query: CallbackQuery, text: str, **kw) -> None:
    """edit_text с защитой: сообщение может быть недоступно/слишком старое."""
    if query.message is None:
        return
    try:
        await query.message.edit_text(text, **kw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("edit сообщения не удался: %s", exc)


async def on_reminder_callback(query: CallbackQuery) -> None:
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "rem":
        await query.answer()
        return
    _, action, rid_s = parts
    reminder_id = int(rid_s)
    rem = await reminder_store.get(reminder_id)
    if not rem:
        await query.answer("Событие неактивно — создай заново", show_alert=False)
        return

    status = rem["status"]
    user_id = query.from_user.id
    is_owner = user_id == OWNER_CHAT_ID
    now = datetime.now(TIMEZONE)

    if action == "sub":
        # Подписка возможна только на активное напоминание.
        if status != "pending":
            await query.answer(_inactive_note(status), show_alert=False)
            return
        await _toggle_subscription(query, rem, now)
        return

    # Остальные действия (подтверждения) — только автор/владелец.
    if not rs.can_modify(rem, user_id=user_id, is_owner=is_owner):
        await query.answer("Только автор может это сделать", show_alert=True)
        return

    # Конфирм-диалог над уже завершённым/отменённым напоминанием устарел.
    if status not in ("pending", "draft"):
        await query.answer(_inactive_note(status), show_alert=False)
        return

    if action == "ok":      # подтвердить черновик (ЛС)
        await reminder_store.set_status(reminder_id, "pending")
        scheduler.schedule(reminder_id, rem["fire_at"])
        await _safe_edit(query, rs.render_confirm_pm(rem, now) + f"\n\n{E.CHECK} Создано",
                         parse_mode="HTML")
        await query.answer("Готово")
    elif action == "no":    # отменить черновик
        await reminder_store.set_status(reminder_id, "cancelled")
        await _safe_edit(query, f"{E.CROSS} Отменено")
        await query.answer()
    elif action == "upd":   # применить отложенную правку
        await reminder_store.apply_pending_update(reminder_id)
        # Правка может прийти на черновик (ЛС, ещё не подтверждён): подтверждение
        # правки заодно активирует напоминание, иначе job выстрелит вхолостую (_fire
        # пропускает не-pending).
        if status == "draft":
            await reminder_store.set_status(reminder_id, "pending")
        fresh = await reminder_store.get(reminder_id)
        scheduler.schedule(reminder_id, fresh["fire_at"])
        await _refresh_card(query.bot, fresh, now)
        await _safe_edit(query, f"{E.CHECK} Обновлено")
        await query.answer("Обновлено")
    elif action == "undo":  # отказаться от правки
        await reminder_store.clear_pending_update(reminder_id)
        await _safe_edit(query, "Оставил как было")
        await query.answer()
    elif action == "del":   # подтвердить отмену
        await reminder_store.set_status(reminder_id, "cancelled")
        scheduler.unschedule(reminder_id)
        await _safe_edit(query, f"{E.CROSS} Напоминание отменено")
        await query.answer("Отменено")
    elif action == "keep":  # передумал отменять
        await _safe_edit(query, "Оставил напоминание")
        await query.answer()
    else:
        await query.answer()


async def _toggle_subscription(query: CallbackQuery, rem: dict, now: datetime) -> None:
    u = query.from_user
    subscribed = await reminder_store.toggle_subscriber(
        rem["id"], user_id=u.id, first_name=u.first_name, username=u.username)
    count = await reminder_store.count_subscribers(rem["id"])
    # Метка кнопки статична — обновляем лишь счётчик участников в карточке.
    await _safe_edit(query, rs.render_card(rem, count, now), parse_mode="HTML",
                     reply_markup=rs.card_keyboard(rem["id"]))
    await query.answer(
        "Вы подписаны на напоминание" if subscribed else "Вы отписаны от напоминания")


async def _refresh_card(bot: Bot, rem: dict, now: datetime) -> None:
    """Перерисовать публичную карточку после правки (если она есть)."""
    if rem["scope"] != "chat" or not rem["card_message_id"]:
        return
    count = await reminder_store.count_subscribers(rem["id"])
    try:
        await bot.edit_message_text(
            rs.render_card(rem, count, now), chat_id=rem["chat_id"],
            message_id=rem["card_message_id"], parse_mode="HTML",
            reply_markup=rs.card_keyboard(rem["id"]))
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh карточки не удался: %s", exc)
