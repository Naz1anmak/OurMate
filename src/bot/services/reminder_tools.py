"""Тулы напоминаний для tool use + их JSON-схемы и реестр."""
import functools
import logging
from datetime import datetime
from typing import Optional

from src.bot.services.llm_tools import ToolRegistry, ToolSpec
from src.bot.services.reminder_store import reminder_store
from src.bot.services import reminder_service as rs
from src.config.settings import TIMEZONE
from src.core.emoji import E

logger = logging.getLogger(__name__)


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(TIMEZONE)


async def create_reminder(when_iso: str, text: str, *, tool_context: dict,
                          store=reminder_store, scheduler=None,
                          now: Optional[datetime] = None) -> dict:
    """Создаёт напоминание. Группа → карточка + job; ЛС → черновик + подтверждение."""
    now = _now(now)
    try:
        fire_dt = datetime.fromisoformat(when_iso)
    except (ValueError, TypeError):
        return {"ok": False, "error": "bad_time"}
    # LLM иногда отдаёт время без TZ — локализуем в TIMEZONE, иначе сравнение с aware now упадёт.
    if fire_dt.tzinfo is None:
        fire_dt = fire_dt.replace(tzinfo=TIMEZONE)
    when_iso = fire_dt.isoformat()
    if fire_dt <= now:
        return {"ok": False, "error": "past"}
    if not (text or "").strip():
        return {"ok": False, "error": "empty_text"}

    bot = tool_context["bot"]
    chat_id = tool_context["chat_id"]
    author_id = tool_context["user_id"]
    is_group = tool_context["is_group"]
    # Групповые напоминания — только в основной беседе. В чужих группах не создаём
    # (в ЛС остаётся доступно всем — там is_group=False).
    if is_group and not tool_context.get("is_group_main"):
        return {"ok": False, "error": "foreign_group"}
    scope = "chat" if is_group else "self"
    status = "pending" if is_group else "draft"

    rid = await store.add(text=text.strip(), fire_at=when_iso, scope=scope,
                          chat_id=chat_id, author_id=author_id, status=status)
    rem = await store.get(rid)

    if is_group:
        msg = await bot.send_message(
            chat_id, rs.render_card(rem, 0, now), parse_mode="HTML",
            reply_markup=rs.card_keyboard(rid))
        await store.set_card_message_id(rid, msg.message_id)
        if scheduler is not None:
            scheduler.schedule(rid, when_iso)
    else:
        await bot.send_message(
            chat_id, rs.render_confirm_pm(rem, now), parse_mode="HTML",
            reply_markup=rs.confirm_keyboard(rid, "ok", "no"))

    return {"ok": True, "id": rid, "scope": scope,
            "when": rs.humanize_dt(fire_dt, now), "posted": True}


async def list_reminders(*, tool_context: dict, store=reminder_store,
                         now: Optional[datetime] = None) -> dict:
    now = _now(now)
    if tool_context["is_group"]:
        items = await store.list_pending_for_chat(tool_context["chat_id"])
        header = "Напоминания беседы"
    else:
        items = await store.list_pending_for_author(tool_context["user_id"])
        header = "Твои напоминания"
    summary = [{"id": r["id"], "text": r["text"],
                "when": rs.humanize_dt(rs.parse_dt(r["fire_at"]), now)} for r in items]
    return {"count": len(items), "reminders": summary,
            "_deferred": [rs.render_list(items, header=header, now=now)]}


async def update_reminder(reminder_id: int, *, tool_context: dict,
                          new_when_iso: Optional[str] = None,
                          new_text: Optional[str] = None,
                          store=reminder_store, scheduler=None,
                          now: Optional[datetime] = None) -> dict:
    now = _now(now)
    rem = await store.get(reminder_id)
    if not rem or rem["status"] not in ("pending", "draft"):
        return {"ok": False, "error": "not_found"}
    if not rs.can_modify(rem, user_id=tool_context["user_id"],
                         is_owner=tool_context["is_owner"]):
        return {"ok": False, "error": "forbidden"}
    if new_when_iso:
        try:
            ndt = datetime.fromisoformat(new_when_iso)
        except (ValueError, TypeError):
            return {"ok": False, "error": "bad_time"}
        if ndt.tzinfo is None:
            ndt = ndt.replace(tzinfo=TIMEZONE)
        new_when_iso = ndt.isoformat()
        if ndt <= now:
            return {"ok": False, "error": "past"}

    await store.set_pending_update(reminder_id, text=new_text, fire_at=new_when_iso)
    diff = rs.make_diff(rem, new_text=new_text, new_fire_at=new_when_iso, now=now)
    await tool_context["bot"].send_message(
        tool_context["chat_id"], diff, parse_mode="HTML",
        reply_markup=rs.confirm_keyboard(reminder_id, "upd", "undo"))
    return {"ok": True, "id": reminder_id, "awaiting_confirm": True}


async def cancel_reminder(reminder_id: int, *, tool_context: dict,
                          store=reminder_store, scheduler=None,
                          now: Optional[datetime] = None) -> dict:
    now = _now(now)
    rem = await store.get(reminder_id)
    if not rem or rem["status"] not in ("pending", "draft"):
        return {"ok": False, "error": "not_found"}
    if not rs.can_modify(rem, user_id=tool_context["user_id"],
                         is_owner=tool_context["is_owner"]):
        return {"ok": False, "error": "forbidden"}
    await tool_context["bot"].send_message(
        tool_context["chat_id"],
        f"{E.CROSS} Отменить «{rem['text']}» ({rs.humanize_dt(rs.parse_dt(rem['fire_at']), now)})?",
        parse_mode="HTML", reply_markup=rs.confirm_keyboard(reminder_id, "del", "keep"))
    return {"ok": True, "id": reminder_id, "awaiting_confirm": True}


CREATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_reminder",
        "description": (
            "Создать напоминание. Вызывай, когда пользователь просит напомнить о чём-то "
            "(«напомни завтра в 9 про зачёт», «напомни всем в пятницу про созвон»). "
            "Время разрешай из контекста времени в ISO 8601 с часовым поясом. "
            "После вызова бот САМ отправит карточку (в группе) или подтверждение (в ЛС) — "
            "не дублируй детали, ответь одной короткой фразой."),
        "parameters": {
            "type": "object",
            "properties": {
                "when_iso": {"type": "string",
                             "description": "Дата-время в ISO 8601 с TZ, напр. 2026-06-05T18:00:00+03:00."},
                "text": {"type": "string", "description": "О чём напомнить (без даты)."},
            },
            "required": ["when_iso", "text"],
        },
    },
}

LIST_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_reminders",
        "description": ("Показать активные напоминания (в группе — беседы, в ЛС — личные). "
                        "Список бот покажет сам — ответь кратко. Используй id из ответа "
                        "для update_reminder/cancel_reminder."),
        "parameters": {"type": "object", "properties": {}},
    },
}

UPDATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_reminder",
        "description": ("Изменить время и/или текст напоминания. Сначала получи id через "
                        "list_reminders. Бот покажет diff и спросит подтверждение — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer"},
                "new_when_iso": {"type": "string", "description": "Новое время ISO 8601 с TZ (опц.)."},
                "new_text": {"type": "string", "description": "Новый текст (опц.)."},
            },
            "required": ["reminder_id"],
        },
    },
}

CANCEL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cancel_reminder",
        "description": ("Отменить напоминание по id (сначала list_reminders). "
                        "Бот спросит подтверждение — ответь кратко."),
        "parameters": {
            "type": "object",
            "properties": {"reminder_id": {"type": "integer"}},
            "required": ["reminder_id"],
        },
    },
}


def build_reminder_registry(*, scheduler) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("create_reminder", ToolSpec(
        schema=CREATE_SCHEMA,
        func=functools.partial(create_reminder, scheduler=scheduler), gate=None))
    reg.register("list_reminders", ToolSpec(schema=LIST_SCHEMA, func=list_reminders, gate=None))
    reg.register("update_reminder", ToolSpec(
        schema=UPDATE_SCHEMA,
        func=functools.partial(update_reminder, scheduler=scheduler), gate=None))
    reg.register("cancel_reminder", ToolSpec(
        schema=CANCEL_SCHEMA,
        func=functools.partial(cancel_reminder, scheduler=scheduler), gate=None))
    return reg
