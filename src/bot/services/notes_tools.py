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


async def _refresh_card(tool_context: dict, store, note: dict) -> None:
    """Показать актуальную карточку. Всегда редактируем существующую НА МЕСТЕ
    (карточка может быть закреплена — пересылать нельзя); новую шлём только если
    карточки ещё нет или её удалили из чата."""
    members = await store.members(note["id"])
    text = ns.render_card(note, members)
    kb = ns.card_keyboard(note["id"])
    bot, chat_id = tool_context["bot"], tool_context["chat_id"]
    card_id = note.get("card_message_id")
    if card_id:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=card_id,
                                        parse_mode="HTML", reply_markup=kb)
            return
        except Exception as exc:  # noqa: BLE001 — карточку удалили/слишком старая → шлём новую
            logger.debug("notes: edit карточки #%s не удался, шлём новую: %s", card_id, exc)
    msg = await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
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
    # Карточка уже есть в чате — не плодим новую с кнопками, просто указываем на неё
    # коротким reply. Новую карточку шлём только если её нет/удалили.
    card_id = note.get("card_message_id")
    if card_id:
        try:
            await tool_context["bot"].send_message(
                tool_context["chat_id"], f"{E.POINT_UP} Вот", parse_mode="HTML",
                reply_to_message_id=card_id)
            return {"ok": True, "id": note["id"], "_silent": True,
                    "_context_note": f"[указал reply на карточку «{note['title']}»]"}
        except Exception as exc:  # noqa: BLE001 — карточку удалили → пришлём заново ниже
            logger.debug("notes: reply на карточку #%s не удался: %s", card_id, exc)
    await _refresh_card(tool_context, store, note)
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[показана карточка списка «{note['title']}»]"}


CREATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_list",
        "description": (
            "Создать общий список/очередь в беседе («заведи список на сдачу», «создай очередь»). "
            "Название обязательно. ВСЕГДА вызывай этот инструмент для создания — никогда не "
            "сообщай, что список создан, не вызвав его. Бот САМ отправит сообщение с выбором "
            "формата (официальный/неофициальный) и кнопками — ответь одной короткой фразой, "
            "детали не дублируй."),
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
            "Показать список («пришли список X», «покажи очередь»). Бот сам укажет на "
            "уже существующую карточку коротким reply (или пришлёт её, если карточки нет) — "
            "новую с кнопками не плодит. Если название не указано и список один — покажи его; "
            "если несколько — вернётся ambiguous со списком названий, переспроси какой. "
            "Ответь совсем кратко."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка (опц.)."},
            },
        },
    },
}


def _resolve_target(who: str, tool_context: dict, users) -> dict:
    """Возвращает {'user_id':..,'username':..,'name':..} | {'error': 'ambiguous'/'unresolved', ...}.

    'name' — имя аккаунта для неофициального рендера (может быть None)."""
    reply_user = tool_context.get("reply_user")
    if reply_user and reply_user.get("user_id"):
        return {"user_id": reply_user["user_id"], "username": reply_user.get("username"),
                "name": reply_user.get("name")}
    mentioned = tool_context.get("mentioned_users") or []
    if mentioned:
        m = mentioned[0]
        return {"user_id": m["user_id"], "username": m.get("username"), "name": m.get("name")}
    who = (who or "").strip()
    # Числовой tg_id: принимаем, но пометим на проверку членства в беседе.
    digits = who.lstrip("@")
    if digits.isdigit():
        return {"user_id": int(digits), "username": None, "needs_verify": True}
    if who.startswith("@") or (who and " " not in who):
        uid = get_user_id_by_username(who, users)
        if uid is not None:
            u = next((x for x in users if x.user_id == uid), None)
            return {"user_id": uid, "username": who.lstrip("@"),
                    "name": u.name if u else None}
    if who:
        found = find_users_by_fullname(who, users)
        if len(found) == 1:
            return {"user_id": found[0].user_id, "username": found[0].username,
                    "name": found[0].name}
        if len(found) > 1:
            return {"error": "ambiguous",
                    "candidates": [f"{u.last_name} {u.name}".strip() for u in found]}
    return {"error": "unresolved"}


async def _fetch_chat_user(tool_context: dict, user_id: int):
    """Для добавления по сырому tg_id: вернуть объект user из getChatMember
    (там есть full_name/username) или None, если человека нет в беседе."""
    try:
        m = await tool_context["bot"].get_chat_member(tool_context["chat_id"], user_id)
        if getattr(m, "status", None) in ("left", "kicked"):
            return None
        return getattr(m, "user", None)
    except Exception as exc:  # noqa: BLE001
        logger.debug("notes: get_chat_member(%s) не удался: %s", user_id, exc)
        return None


async def add_to_list(title: str, who: str = "", position: int = 0, *, tool_context: dict,
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
        # @ник резолвится только через ростер ДР (Bot API не даёт username→id);
        # для остальных надёжный путь — реплай на сообщение человека.
        hint = ("Ответь (reply) на сообщение этого человека и повтори «добавь его в список», "
                "либо пришли его числовой tg_id — так я смогу его добавить."
                if target["error"] == "unresolved" else None)
        return {"ok": False, "error": target["error"],
                "candidates": target.get("candidates"), "hint": hint}
    if target.get("needs_verify"):
        u = await _fetch_chat_user(tool_context, target["user_id"])
        if u is None:
            return {"ok": False, "error": "unresolved",
                    "hint": "Пользователь с таким id не найден в этой беседе."}
        # Из getChatMember забираем ник и имя аккаунта — чтобы в карточке было имя, а не цифры.
        target["username"] = getattr(u, "username", None)
        target["name"] = getattr(u, "full_name", None)
    added = await store.add_member(note["id"], user_id=target["user_id"],
                                   username=target.get("username"),
                                   tg_name=target.get("name"))
    try:
        pos = int(position)
    except (TypeError, ValueError):
        pos = 0
    if pos >= 1:  # «добавь на N место» — сразу ставим на нужную позицию
        await store.move_member(note["id"], target["user_id"], pos)
    await _refresh_card(tool_context, store, note)
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
            "автоматически; иначе передай @ник, «Фамилия Имя» или числовой tg_id. Работает "
            "независимо от формата списка (формат выбирать заранее НЕ нужно). Можно сразу "
            "указать position — «добавь X на первое место» → position=1. Несколько совпадений → "
            "ambiguous с кандидатами, переспроси. Карточку бот перерисует сам — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка."},
                "who": {"type": "string",
                        "description": "@ник, «Фамилия Имя» или числовой tg_id "
                                       "(можно пусто, если это reply)."},
                "position": {"type": "integer",
                             "description": "Куда поставить (1-based). 0/пропуск — в конец."},
            },
            "required": ["title"],
        },
    },
}


def _resolve_member(who: str, tool_context: dict, members: list[dict], users) -> dict:
    """Кого убрать из списка. В отличие от _resolve_target — ищем среди участников:
    по reply/меншену, номеру позиции, username участника, а также @нику/ФИО из ростера."""
    reply_user = tool_context.get("reply_user")
    if reply_user and reply_user.get("user_id"):
        return {"user_id": reply_user["user_id"]}
    mentioned = tool_context.get("mentioned_users") or []
    if mentioned:
        return {"user_id": mentioned[0]["user_id"]}
    who = (who or "").strip()
    if not who:
        return {"error": "unresolved"}
    digits = who.lstrip("@")
    if digits.isdigit():
        n = int(digits)
        if 1 <= n <= len(members):  # номер позиции в карточке
            return {"user_id": members[n - 1]["user_id"]}
        return {"user_id": n}  # трактуем как сырой tg_id
    # Сопоставляем с участниками списка: по username и по имени аккаунта (tg_name),
    # т.к. в карточке показывается именно tg_name — по нему и просят убрать.
    handle = who.lstrip("@").lower()
    who_l = who.lower()
    hits = []
    for m in members:
        uname = (m.get("username") or "").lower()
        tname = (m.get("tg_name") or "").lower()
        if uname == handle or tname == who_l or (tname and who_l in tname):
            hits.append(m["user_id"])
    uniq = list(dict.fromkeys(hits))
    if len(uniq) == 1:
        return {"user_id": uniq[0]}
    if len(uniq) > 1:
        return {"error": "ambiguous",
                "candidates": [str(u) for u in uniq]}
    # @ник / ФИО через ростер ДР
    if who.startswith("@") or " " not in who:
        uid = get_user_id_by_username(who, users)
        if uid is not None:
            return {"user_id": uid}
    found = find_users_by_fullname(who, users)
    if len(found) == 1:
        return {"user_id": found[0].user_id}
    if len(found) > 1:
        return {"error": "ambiguous",
                "candidates": [f"{u.last_name} {u.name}".strip() for u in found]}
    return {"error": "unresolved"}


async def remove_from_list(title: str, who: str = "", *, tool_context: dict,
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
    members = await store.members(note["id"])
    target = _resolve_member(who, tool_context, members, users)
    if "error" in target:
        return {"ok": False, "error": target["error"],
                "candidates": target.get("candidates")}
    removed = await store.remove_member(note["id"], target["user_id"])
    if not removed:
        return {"ok": False, "error": "not_member"}
    await _refresh_card(tool_context, store, note)
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[из списка «{note['title']}» убран участник]"}


REMOVE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "remove_from_list",
        "description": (
            "Убрать ОДНОГО участника из списка (только автор списка или владелец беседы). "
            "Кого: если запрос — ответ (reply) на сообщение человека, бот возьмёт его сам; "
            "иначе @ник, «Фамилия Имя», номер позиции в списке (например «убери третьего» → 3) "
            "или числовой tg_id. Несколько совпадений по ФИО → ambiguous, переспроси. "
            "Карточку бот перерисует сам — ответь кратко. Не путать с clear_list (убрать всех)."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка."},
                "who": {"type": "string",
                        "description": "@ник, «Фамилия Имя», номер позиции или tg_id "
                                       "(можно пусто, если это reply)."},
            },
            "required": ["title"],
        },
    },
}


async def move_in_list(title: str, who: str = "", position: int = 0, *, tool_context: dict,
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
    members = await store.members(note["id"])
    try:
        pos = int(position)
    except (TypeError, ValueError):
        pos = 0
    if pos < 1:
        return {"ok": False, "error": "bad_position"}
    target = _resolve_member(who, tool_context, members, users)
    if "error" in target:
        return {"ok": False, "error": target["error"],
                "candidates": target.get("candidates")}
    moved = await store.move_member(note["id"], target["user_id"], pos)
    if not moved:
        return {"ok": False, "error": "not_member"}
    await _refresh_card(tool_context, store, note)
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[в списке «{note['title']}» участник перемещён на позицию {pos}]"}


MOVE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "move_in_list",
        "description": (
            "Переставить участника на другую позицию в списке (только автор списка или "
            "владелец беседы). Кого — как в remove_from_list (reply / @ник / «Фамилия Имя» / "
            "текущий номер позиции / tg_id); position — новая 1-based позиция "
            "(«перемести третьего на первое место» → who=3, position=1). "
            "Карточку бот перерисует сам — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка."},
                "who": {"type": "string",
                        "description": "@ник, «Фамилия Имя», текущий номер позиции или tg_id "
                                       "(можно пусто, если это reply)."},
                "position": {"type": "integer", "description": "Новая позиция (с 1)."},
            },
            "required": ["title", "position"],
        },
    },
}


async def swap_in_list(title: str, a: str = "", b: str = "", *, tool_context: dict,
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
    members = await store.members(note["id"])
    ta = _resolve_member(a, tool_context, members, users)
    tb = _resolve_member(b, tool_context, members, users)
    for t in (ta, tb):
        if "error" in t:
            return {"ok": False, "error": t["error"], "candidates": t.get("candidates")}
    if not await store.swap_members(note["id"], ta["user_id"], tb["user_id"]):
        return {"ok": False, "error": "not_member"}
    await _refresh_card(tool_context, store, note)
    return {"ok": True, "id": note["id"], "_silent": True,
            "_context_note": f"[в списке «{note['title']}» двое поменяны местами]"}


SWAP_SCHEMA = {
    "type": "function",
    "function": {
        "name": "swap_in_list",
        "description": (
            "Поменять местами ДВУХ участников списка («поменяй 1 и 3 местами», «поменяй "
            "@ник и Иванова»; только автор списка или владелец). a и b — каждый как в "
            "move_in_list (reply / @ник / «Фамилия Имя» / номер позиции / tg_id). Именно для "
            "«поменять местами» используй этот тул, а НЕ move_in_list. Карточку бот перерисует "
            "сам — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название списка."},
                "a": {"type": "string", "description": "Первый участник (ник/ФИО/номер/tg_id)."},
                "b": {"type": "string", "description": "Второй участник (ник/ФИО/номер/tg_id)."},
            },
            "required": ["title", "a", "b"],
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
    reg.register("remove_from_list",
                 ToolSpec(schema=REMOVE_SCHEMA, func=remove_from_list, gate=None))
    reg.register("move_in_list", ToolSpec(schema=MOVE_SCHEMA, func=move_in_list, gate=None))
    reg.register("swap_in_list", ToolSpec(schema=SWAP_SCHEMA, func=swap_in_list, gate=None))
    reg.register("delete_list", ToolSpec(schema=DELETE_SCHEMA, func=delete_list, gate=None))
    reg.register("clear_list", ToolSpec(schema=CLEAR_SCHEMA, func=clear_list, gate=None))
    return reg
