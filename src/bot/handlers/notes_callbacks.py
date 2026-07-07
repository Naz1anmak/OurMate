"""Колбэки списков (list:*): выбор формата, запись/выход, подтверждения удаления/очистки."""
import logging
from html import escape

from aiogram.types import CallbackQuery, ForceReply

from src.bot.services.notes_store import notes_store
from src.bot.services import notes_service as ns
from src.bot.services.birthday_service import birthday_service
from src.config.settings import OWNER_CHAT_ID

logger = logging.getLogger(__name__)

# Ожидания настоящего имени (formal, нет в ростере): {(chat_id, prompt_message_id): (note_id, user_id)}.
# In-memory — переживать рестарт не нужно (короткоживущее), как кулдаун в ping_service.
_pending_name: dict[tuple[int, int], tuple[int, int]] = {}


def _in_roster(user_id: int) -> bool:
    return any(u.user_id == user_id for u in birthday_service.users)


async def _require_can_modify(query: CallbackQuery, note_id: int, chat_id: int) -> dict | None:
    """Гейт мутирующих колбэков (fmt/del/clr): вернуть note, если можно, иначе None + алерт.

    Кнопки в группе видны всем, а callback_data подделываем — поэтому право на
    изменение проверяем на сервере: автор списка или владелец беседы, та же беседа.
    """
    note = await notes_store.get(note_id)
    is_owner = query.from_user.id == OWNER_CHAT_ID
    if (not note or note["chat_id"] != chat_id
            or not ns.can_modify(note, user_id=query.from_user.id, is_owner=is_owner)):
        await query.answer("Только автор списка или владелец беседы", show_alert=True)
        return None
    return note


async def _rerender_card(message, note_id: int) -> None:
    note = await notes_store.get(note_id)
    if not note:
        return
    members = await notes_store.members(note_id)
    try:
        await message.edit_text(ns.render_card(note, members),
                                reply_markup=ns.card_keyboard(note_id), parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        logger.debug("notes: edit карточки не удался: %s", exc)


async def _refresh_stored_card(bot, chat_id: int, note_id: int) -> None:
    """Перерисовать карточку по её сохранённому message_id, а не по сообщению с кнопкой.

    Кнопки подтверждения (clr/del) висят на ОТДЕЛЬНОМ сообщении-вопросе, а не на самой
    карточке — правим карточку на месте (она может быть закреплена), вопрос трогаем отдельно."""
    note = await notes_store.get(note_id)
    if not note:
        return
    card_id = note.get("card_message_id")
    if not card_id:
        return
    members = await notes_store.members(note_id)
    try:
        await bot.edit_message_text(ns.render_card(note, members), chat_id=chat_id,
                                    message_id=card_id, reply_markup=ns.card_keyboard(note_id),
                                    parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        logger.debug("notes: перерисовка карточки #%s не удалась: %s", card_id, exc)


async def on_notes_callback(query: CallbackQuery) -> None:
    parts = (query.data or "").split(":")
    if len(parts) < 2 or parts[0] != "list" or query.message is None:
        await query.answer()
        return
    action = parts[1]
    chat_id = query.message.chat.id
    user = query.from_user

    if action == "fmt":  # list:fmt:<0|1>:<id>
        if parts[2] not in ("0", "1"):
            await query.answer()
            return
        formal = parts[2] == "1"
        note_id = int(parts[3])
        if await _require_can_modify(query, note_id, chat_id) is None:
            return
        await notes_store.set_formal(note_id, formal)
        await notes_store.set_card_message(note_id, query.message.message_id)
        await _rerender_card(query.message, note_id)
        await query.answer("Формат выбран")
        return

    note_id = int(parts[2])

    if action == "join":
        await notes_store.toggle_member(note_id, user_id=user.id, username=user.username,
                                        tg_name=user.full_name)
        note = await notes_store.get(note_id)
        # Официальный список + нет в ростере + всё ещё записан → попросить настоящее имя.
        if (note and note["formal"] and await notes_store.is_member(note_id, user.id)
                and not _in_roster(user.id)):
            prompt = await query.message.answer(
                "Вас нет в базе — ответьте на это сообщение своим настоящим именем "
                "(например «Иванов Иван»).",
                reply_markup=ForceReply(selective=True))
            _pending_name[(chat_id, prompt.message_id)] = (note_id, user.id)
        await _rerender_card(query.message, note_id)
        await query.answer("Вы записаны")
        return

    if action == "leave":
        removed = await notes_store.remove_member(note_id, user.id)
        await _rerender_card(query.message, note_id)
        await query.answer("Вы вышли" if removed else "Вас и не было в списке")
        return

    if action == "del":
        note = await _require_can_modify(query, note_id, chat_id)
        if note is None:
            return
        title = note["title"]
        card_id = note.get("card_message_id")
        await notes_store.delete(note_id)
        if card_id:  # убираем саму карточку (закреплённую/старую удалить нельзя — молча пропускаем)
            try:
                await query.message.bot.delete_message(chat_id, card_id)
            except Exception:  # noqa: BLE001
                pass
        try:
            await query.message.edit_text(f"Список «{escape(title)}» удалён.", parse_mode="HTML")
        except Exception:  # noqa: BLE001
            pass
        await query.answer("Удалено")
        return

    if action == "keep":
        await query.answer("Оставил как есть")
        return

    if action == "clr":
        note = await _require_can_modify(query, note_id, chat_id)
        if note is None:
            return
        await notes_store.clear(note_id)
        # Правим настоящую карточку на месте; сообщение-вопрос убираем, чтобы не плодить дубль.
        await _refresh_stored_card(query.message.bot, chat_id, note_id)
        try:
            await query.message.delete()
        except Exception:  # noqa: BLE001
            pass
        await query.answer("Список очищен")
        return

    if action == "keepall":
        await query.answer("Оставил как есть")
        return

    if action == "undo":
        snap = await notes_store.get_undo(note_id)
        if not snap:
            await query.answer("Отменять нечего", show_alert=True)
            return
        if user.id != snap["author_id"]:
            await query.answer("Отменить может только тот, кто сделал изменение",
                               show_alert=True)
            return
        await notes_store.restore_members(note_id, snap["members"])
        await _refresh_stored_card(query.message.bot, chat_id, note_id)
        await notes_store.clear_undo(note_id)
        try:
            await query.message.edit_text("Отменено")
        except Exception as exc:  # noqa: BLE001 — реплику могли удалить
            logger.debug("notes: правка реплики undo не удалась: %s", exc)
        await query.answer("Отменено")
        return

    await query.answer()
