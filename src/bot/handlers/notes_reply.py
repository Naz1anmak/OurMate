"""Детерминированный разбор реплаев на карточку списка (уточнение) и запрос имени (force-reply)."""
import logging

from aiogram.types import Message

from src.bot.services.notes_store import notes_store
from src.bot.services import notes_service as ns
from src.bot.handlers.notes_callbacks import _pending_name

logger = logging.getLogger(__name__)


async def _rerender_from_message(message: Message, note_id: int) -> None:
    """Перерисовать карточку по её сохранённому message_id."""
    note = await notes_store.get(note_id)
    if not note or not note.get("card_message_id"):
        return
    members = await notes_store.members(note_id)
    try:
        await message.bot.edit_message_text(
            ns.render_card(note, members), chat_id=message.chat.id,
            message_id=note["card_message_id"], reply_markup=ns.card_keyboard(note_id),
            parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        logger.debug("notes: перерисовка карточки по реплаю не удалась: %s", exc)


async def handle_notes_reply(message: Message) -> bool:
    """True — сообщение поглощено (уточнение/имя). False — не про списки, пусть идёт дальше."""
    reply = getattr(message, "reply_to_message", None)
    if reply is None or not (message.text or "").strip():
        return False
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.strip()

    # 1) Реплай на force-reply-запрос имени.
    key = (chat_id, reply.message_id)
    pending = _pending_name.get(key)
    if pending is not None:
        note_id, expected_uid = pending
        if user_id != expected_uid:
            return False  # чужой реплай на запрос — не наш
        await notes_store.set_name(note_id, user_id, text)
        _pending_name.pop(key, None)
        await _rerender_from_message(message, note_id)
        return True

    # 2) Реплай на карточку списка → уточнение.
    note = await notes_store.get_by_card_message(chat_id, reply.message_id)
    if note is None:
        return False
    if not await notes_store.is_member(note["id"], user_id):
        await message.reply("Сначала запишитесь кнопкой «Записаться» под списком.")
        return True
    # «-»/«—»/«убрать» очищают уточнение; пустой рендер его просто не покажет.
    note_text = "" if text in ("-", "—", "–", "убрать", "очистить") else text
    await notes_store.set_note(note["id"], user_id, note_text)
    await _rerender_from_message(message, note["id"])
    return True
