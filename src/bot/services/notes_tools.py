"""Тулы списков для tool use + JSON-схемы и реестр. Образец — reminder_tools."""
import logging
from html import escape

from src.bot.services.llm_tools import ToolRegistry, ToolSpec
from src.bot.services.notes_store import notes_store
from src.bot.services import notes_service as ns
from src.utils.text_utils import get_user_id_by_username, find_users_by_fullname
from src.core.emoji import E

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
        chat_id, f"Список «{escape(title)}» — какой формат?",
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


def _resolve_target(who: str, tool_context: dict, users) -> dict:
    """Возвращает {'user_id':..,'username':..} | {'error': 'ambiguous'/'unresolved', ...}."""
    reply_user = tool_context.get("reply_user")
    if reply_user and reply_user.get("user_id"):
        return {"user_id": reply_user["user_id"], "username": reply_user.get("username")}
    mentioned = tool_context.get("mentioned_users") or []
    if mentioned:
        m = mentioned[0]
        return {"user_id": m["user_id"], "username": m.get("username")}
    who = (who or "").strip()
    if who.startswith("@") or (who and " " not in who):
        uid = get_user_id_by_username(who, users)
        if uid is not None:
            return {"user_id": uid, "username": who.lstrip("@")}
    if who:
        found = find_users_by_fullname(who, users)
        if len(found) == 1:
            return {"user_id": found[0].user_id, "username": found[0].username}
        if len(found) > 1:
            return {"error": "ambiguous",
                    "candidates": [f"{u.last_name} {u.name}".strip() for u in found]}
    return {"error": "unresolved"}


async def add_to_list(title: str, who: str = "", *, tool_context: dict,
                      store=notes_store, users=None) -> dict:
    if _foreign(tool_context):
        return {"ok": False, "error": "foreign_group"}
    if users is None:
        from src.bot.services.birthday_service import birthday_service
        users = birthday_service.users
    note = await store.get_by_title(tool_context["chat_id"], (title or "").strip())
    if not note:
        return {"ok": False, "error": "not_found"}
    if not ns.can_modify(note, user_id=tool_context["user_id"],
                         is_owner=tool_context["is_owner"]):
        return {"ok": False, "error": "forbidden"}
    target = _resolve_target(who, tool_context, users)
    if "error" in target:
        return {"ok": False, "error": target["error"],
                "candidates": target.get("candidates")}
    added = await store.add_member(note["id"], user_id=target["user_id"],
                                   username=target.get("username"))
    await _send_card(tool_context, store, note)
    verb = "добавлен" if added else "уже в списке"
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[в список «{note['title']}»: пользователь {verb}]"}


ADD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "add_to_list",
        "description": (
            "Добавить ДРУГОГО человека в список (только автор списка или владелец беседы). "
            "Укажи, кого: если запрос — ответ (reply) на сообщение человека, бот возьмёт его "
            "автоматически; иначе передай @ник или «Фамилия Имя». Несколько совпадений → "
            "ambiguous с кандидатами, переспроси. Карточку бот перерисует сам — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка."},
                "who": {"type": "string",
                        "description": "@ник или «Фамилия Имя» (можно пусто, если это reply)."},
            },
            "required": ["title"],
        },
    },
}


async def _guarded(title, tool_context, store):
    """Общий гейт для delete/clear: вернуть (note, None) или (None, err_dict)."""
    if _foreign(tool_context):
        return None, {"ok": False, "error": "foreign_group"}
    note = await store.get_by_title(tool_context["chat_id"], (title or "").strip())
    if not note:
        return None, {"ok": False, "error": "not_found"}
    if not ns.can_modify(note, user_id=tool_context["user_id"],
                         is_owner=tool_context["is_owner"]):
        return None, {"ok": False, "error": "forbidden"}
    return note, None


async def delete_list(title: str, *, tool_context: dict, store=notes_store) -> dict:
    note, err = await _guarded(title, tool_context, store)
    if err:
        return err
    await tool_context["bot"].send_message(
        tool_context["chat_id"],
        f"{E.CROSS} Удалить список «{escape(note['title'])}» целиком?",
        parse_mode="HTML", reply_markup=ns.confirm_keyboard(note["id"], "del", "keep"))
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[предложено удаление списка «{note['title']}», ждёт подтверждения]"}


async def clear_list(title: str, *, tool_context: dict, store=notes_store) -> dict:
    note, err = await _guarded(title, tool_context, store)
    if err:
        return err
    await tool_context["bot"].send_message(
        tool_context["chat_id"],
        f"{E.CROSS} Очистить список «{escape(note['title'])}» (убрать всех участников)?",
        parse_mode="HTML", reply_markup=ns.confirm_keyboard(note["id"], "clr", "keepall"))
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[предложена очистка списка «{note['title']}», ждёт подтверждения]"}


DELETE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "delete_list",
        "description": ("Удалить список целиком (автор списка или владелец). Бот спросит "
                        "подтверждение кнопками — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
}

CLEAR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "clear_list",
        "description": ("Очистить список — убрать всех участников, но оставить сам список "
                        "(автор или владелец). Бот спросит подтверждение — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
}


def build_notes_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("create_list", ToolSpec(schema=CREATE_SCHEMA, func=create_list, gate=None))
    reg.register("show_list", ToolSpec(schema=SHOW_SCHEMA, func=show_list, gate=None))
    reg.register("add_to_list", ToolSpec(schema=ADD_SCHEMA, func=add_to_list, gate=None))
    reg.register("delete_list", ToolSpec(schema=DELETE_SCHEMA, func=delete_list, gate=None))
    reg.register("clear_list", ToolSpec(schema=CLEAR_SCHEMA, func=clear_list, gate=None))
    return reg
