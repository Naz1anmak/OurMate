"""Бизнес-логика пинг-листа: панель, рендер меншенов, детектор @all, кулдаун (в памяти)."""
import html
import time

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config.settings import PING_COOLDOWN_SECONDS
from src.core.emoji import E

MENTION_BATCH = 50

# Кулдаун @all в памяти: {chat_id: last_fired_monotonic}. Переживать рестарт не нужно.
_last_fired: dict[int, float] = {}


def has_all_trigger(text: str) -> bool:
    """Есть ли в тексте отдельный токен @all (регистронезависимо, без хвостовой пунктуации)."""
    if not text:
        return False
    for token in text.split():
        if token.lower().strip(".,!?;:") == "@all":
            return True
    return False


def panel_text(count: int) -> str:
    return (
        f"{E.REMINDER} <b>Список для уведомлений</b>\n\n"
        f"Вступайте, чтобы вас звали по <code>@all</code>.\n"
        f"В списке: <b>{count}</b>"
    )


def panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Вступить",
                             callback_data="ping:join", style="success"),
        InlineKeyboardButton(text="Выйти",
                             callback_data="ping:leave", style="danger"),
    ]])


def _mention(user_id: int, name: str | None) -> str:
    safe = html.escape(name or str(user_id))
    return f'<a href="tg://user?id={user_id}">{safe}</a>'


def build_ping_messages(members: list[dict]) -> list[str]:
    """Список текстов (батчи по MENTION_BATCH меншенов) для пинга. Первый — с шапкой."""
    mentions = [_mention(m["user_id"], m.get("first_name")) for m in members]
    batches = [mentions[i:i + MENTION_BATCH] for i in range(0, len(mentions), MENTION_BATCH)]
    header = f"{E.REMINDER} <b>Общий сбор!</b>\n\n"
    return [
        (header if idx == 0 else "") + " ".join(batch)
        for idx, batch in enumerate(batches)
    ]


def cooldown_remaining(chat_id: int, now: float | None = None) -> float:
    """Сколько секунд осталось до следующего разрешённого @all (0 — можно звать)."""
    now = time.monotonic() if now is None else now
    last = _last_fired.get(chat_id)
    if last is None:
        return 0.0
    remaining = PING_COOLDOWN_SECONDS - (now - last)
    return remaining if remaining > 0 else 0.0


def mark_fired(chat_id: int, now: float | None = None) -> None:
    _last_fired[chat_id] = time.monotonic() if now is None else now


def reset_cooldown() -> None:
    """Сброс кулдауна (для тестов)."""
    _last_fired.clear()
