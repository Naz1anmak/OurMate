"""Тулы списков для tool use + JSON-схемы и реестр. Образец — reminder_tools."""
import logging

from src.bot.services.llm_tools import ToolRegistry, ToolSpec
from src.bot.services.notes_store import notes_store
from src.bot.services import notes_service as ns

logger = logging.getLogger(__name__)


def _foreign(tool_context: dict) -> bool:
    """True — не место для списков (списки только в основной беседе)."""
    return not (tool_context.get("is_group") and tool_context.get("is_group_main"))


async def _send_card(tool_context: dict, store, note: dict) -> None:
    """Отправить свежую карточку и запомнить её message_id (для реплай-уточнений)."""
    members = await store.members(note["id"])
    msg = await tool_context["bot"].send_message(
        tool_context["chat_id"], ns.render_card(note, members),
        parse_mode="HTML", reply_markup=ns.card_keyboard(note["id"]))
    await store.set_card_message(note["id"], msg.message_id)


async def create_list(title: str, *, tool_context: dict, store=notes_store) -> dict:
    if _foreign(tool_context):
        return {"ok": False, "error": "foreign_group"}
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "empty_title"}
    chat_id = tool_context["chat_id"]
    if await store.get_by_title(chat_id, title):
        return {"ok": False, "error": "exists"}
    nid = await store.create(chat_id=chat_id, title=title,
                             author_id=tool_context["user_id"], formal=False)
    if nid is None:  # гонка: создали параллельно
        return {"ok": False, "error": "exists"}
    # Сообщение-выбор формата; оно же станет карточкой после выбора (Task 11).
    msg = await tool_context["bot"].send_message(
        chat_id, f"Список «{title}» — какой формат?",
        parse_mode="HTML", reply_markup=ns.format_keyboard(nid))
    await store.set_card_message(nid, msg.message_id)
    note = f"[создан список «{title}» #{nid}, ждёт выбора формата]"
    return {"ok": True, "id": nid, "_silent": True, "_context_note": note}


async def show_list(title: str = "", *, tool_context: dict, store=notes_store) -> dict:
    if _foreign(tool_context):
        return {"ok": False, "error": "foreign_group"}
    chat_id = tool_context["chat_id"]
    title = (title or "").strip()
    if title:
        note = await store.get_by_title(chat_id, title)
        if not note:
            return {"ok": False, "error": "not_found"}
    else:
        notes = await store.list_for_chat(chat_id)
        if not notes:
            return {"ok": False, "error": "not_found"}
        if len(notes) > 1:
            return {"ok": False, "error": "ambiguous", "titles": [n["title"] for n in notes]}
        note = notes[0]
    await _send_card(tool_context, store, note)
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[показана карточка списка «{note['title']}»]"}


CREATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_list",
        "description": (
            "Создать общий список/очередь в беседе («заведи список на сдачу», «создай очередь»). "
            "Название обязательно. Бот САМ отправит сообщение с выбором формата (официальный/"
            "неофициальный) и кнопками — ответь одной короткой фразой, детали не дублируй."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка."},
            },
            "required": ["title"],
        },
    },
}

SHOW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "show_list",
        "description": (
            "Прислать карточку списка с кнопками «Записаться»/«Выйти» («пришли список X», "
            "«покажи очередь»). Если название не указано и список один — покажи его; если "
            "несколько — вернётся ambiguous со списком названий, переспроси какой. "
            "Карточку бот отправит сам — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка (опц.)."},
            },
        },
    },
}


def build_notes_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("create_list", ToolSpec(schema=CREATE_SCHEMA, func=create_list, gate=None))
    reg.register("show_list", ToolSpec(schema=SHOW_SCHEMA, func=show_list, gate=None))
    return reg
