"""Логика и рендер напоминаний: даты, список, карточка, пинг, клавиатуры, права."""
from datetime import datetime
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.core.emoji import E

_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек")
_WD_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

MENTION_CHUNK = 50  # лимит упоминаний на сообщение


def parse_dt(fire_at: str) -> datetime:
    return datetime.fromisoformat(fire_at)


def humanize_dt(dt: datetime, now: datetime) -> str:
    """Сегодня/завтра — словом; остальные — «пт, 5 июн». Время всегда HH:MM."""
    d, today = dt.date(), now.date()
    delta = (d - today).days
    hm = f"{dt:%H:%M}"
    if delta == 0:
        return f"сегодня, {hm}"
    if delta == 1:
        return f"завтра, {hm}"
    return f"{_WD_SHORT[d.weekday()]}, {d.day} {_MONTHS[d.month - 1]}, {hm}"


def render_list(items: list[dict], *, header: str, now: datetime) -> str:
    if not items:
        return (f"{E.REMINDER} <b>{header}</b>\n\nПока напоминаний нет.\n"
                "Создай: «напомни завтра в 9 про зачёт».")
    lines = [f"{E.REMINDER} <b>{header} ({len(items)})</b>", ""]
    for i, r in enumerate(items, 1):
        when = humanize_dt(parse_dt(r["fire_at"]), now)
        lines.append(f"{i}. {escape(r['text'])} — {when}")
    return "\n".join(lines)


def render_card(rem: dict, sub_count: int, now: datetime) -> str:
    when = humanize_dt(parse_dt(rem["fire_at"]), now)
    return (f"{E.REMINDER} <b>Напомню:</b> {escape(rem['text'])}\n"
            f"▎ {when} · участников {sub_count}")


def render_confirm_pm(rem: dict, now: datetime) -> str:
    when = humanize_dt(parse_dt(rem["fire_at"]), now)
    return (f"{E.REMINDER} Напомнить: <b>{escape(rem['text'])}</b>\n"
            f"▎ {when}\n\nСоздаём?")


def render_created(rem: dict, now: datetime) -> str:
    """Подтверждённое состояние черновика (без вопроса «Создаём?»)."""
    when = humanize_dt(parse_dt(rem["fire_at"]), now)
    return (f"{E.REMINDER} Напомню: <b>{escape(rem['text'])}</b>\n"
            f"▎ {when}")


def make_diff(old: dict, *, new_text: str | None, new_fire_at: str | None,
              now: datetime) -> str:
    parts = []
    if new_fire_at and new_fire_at != old["fire_at"]:
        parts.append(f"{humanize_dt(parse_dt(old['fire_at']), now)} → "
                     f"{humanize_dt(parse_dt(new_fire_at), now)}")
    if new_text and new_text != old["text"]:
        parts.append(f"«{escape(old['text'])}» → «{escape(new_text)}»")
    body = "; ".join(parts) if parts else "без изменений"
    return f"{E.THINK_PENCIL} {body}\n\nПрименить?"


def _mention(user_id: int, first_name: str | None) -> str:
    name = escape(first_name or "участник")
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def render_ping(rem: dict, subscribers: list[dict], *, late_note: str | None = None) -> list[str]:
    """HTML-сообщения пинга. Упоминания через tg://user — уведомляют и работают с premium-эмодзи.

    Если подписчиков нет (никто не нажал «Напомни и мне») — одно сообщение без упоминаний.
    """
    head = f"{E.REMINDER} <b>Напоминание:</b> {escape(rem['text'])}"
    if late_note:
        head += f"\n{late_note}"
    if not subscribers:
        return [head]
    chunks: list[str] = []
    for i in range(0, len(subscribers), MENTION_CHUNK):
        batch = subscribers[i:i + MENTION_CHUNK]
        mentions = ", ".join(_mention(s["user_id"], s["first_name"]) for s in batch)
        chunks.append(f"{head}\nДля {mentions}")
    return chunks


def can_modify(rem: dict, *, user_id: int, is_owner: bool) -> bool:
    return is_owner or rem["author_id"] == user_id


# ── Клавиатуры (aiogram 3.26: InlineKeyboardButton.style) ──────────────────

def card_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Одна статичная кнопка-toggle. Метка не зависит от того, кто подписан
    (карточка общая для всех), персональный результат сообщается тостом в callback."""
    btn = InlineKeyboardButton(text="Подписаться / Отписаться",
                               callback_data=f"rem:sub:{reminder_id}", style="primary")
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


def confirm_keyboard(reminder_id: int, ok_action: str, no_action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{E.CHECK} Да", callback_data=f"rem:{ok_action}:{reminder_id}",
                             style="success"),
        InlineKeyboardButton(text=f"{E.CROSS} Отмена", callback_data=f"rem:{no_action}:{reminder_id}",
                             style="danger"),
    ]])
