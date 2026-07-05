"""Логика и рендер списков: карточка, обзор, резолв имени, права. Образцы — ping_service/reminder_service."""
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.core.emoji import E
from src.utils.text_utils import roster_full_name


def _roster():
    # Ленивая ссылка на ростер, чтобы не тянуть birthday_service в тестах рендера.
    from src.bot.services.birthday_service import birthday_service
    return birthday_service.users


def _mention(user_id: int, text: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(text)}</a>'


def resolve_display(member: dict, *, formal: bool, users=None) -> str:
    """HTML-меншен участника. casual — username/имя профиля; formal — ФИО из ростера/override."""
    users = _roster() if users is None else users
    uid = member["user_id"]
    if formal:
        for u in users:
            if u.user_id == uid:
                return _mention(uid, roster_full_name(u))
        if member.get("name_override"):
            return _mention(uid, member["name_override"])
        return _mention(uid, "(имя не указано)")
    label = (member.get("tg_name") or member.get("username")
             or member.get("name_override") or str(uid))
    return _mention(uid, label)


_HINT = ("<i>Для уточнения у имени — ответь на это сообщение; "
         "ответь «-», чтобы убрать уточнение</i>")


def render_card(note: dict, members: list[dict], *, users=None) -> str:
    formal = bool(note.get("formal"))
    head = f"{E.REMINDER} <b>{escape(note['title'])}</b>"
    if not members:
        return f"{head}\n\nПока никто не записался.\n\n{_HINT}"
    lines = [head, ""]
    for i, m in enumerate(members, 1):
        row = f"{i}. {resolve_display(m, formal=formal, users=users)}"
        if m.get("note"):
            row += f" — {escape(m['note'])}"
        lines.append(row)
    lines += ["", f"Всего: {len(members)}", "", _HINT]
    return "\n".join(lines)


def render_overview(notes: list[dict]) -> str:
    if not notes:
        return (f"{E.REMINDER} <b>Списки</b>\n\nСписков пока нет. "
                "Скажи «заведи список …», чтобы создать.")
    lines = [f"{E.REMINDER} <b>Списки ({len(notes)})</b>", ""]
    for n in notes:
        lines.append(f"• <b>{escape(n['title'])}</b> — {n['member_count']} чел.")
    return "\n".join(lines)


def can_modify(note: dict, *, user_id: int, is_owner: bool) -> bool:
    return is_owner or note["author_id"] == user_id


def format_keyboard(note_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Официальный",
                             callback_data=f"list:fmt:1:{note_id}"),
        InlineKeyboardButton(text="Неофициальный",
                             callback_data=f"list:fmt:0:{note_id}"),
    ]])


def card_keyboard(note_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Записаться",
                             callback_data=f"list:join:{note_id}", style="success"),
        InlineKeyboardButton(text="Выйти",
                             callback_data=f"list:leave:{note_id}", style="danger"),
    ]])


def confirm_keyboard(note_id: int, ok_action: str, no_action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{E.CHECK} Да",
                             callback_data=f"list:{ok_action}:{note_id}", style="success"),
        InlineKeyboardButton(text=f"{E.CROSS} Отмена",
                             callback_data=f"list:{no_action}:{note_id}", style="danger"),
    ]])
