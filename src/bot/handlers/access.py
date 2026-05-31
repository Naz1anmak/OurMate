"""Единый источник правды о доступе к командам: классификация и резолв."""
import logging
from dataclasses import dataclass
from enum import Enum, auto

from aiogram.types import Message

from src.bot.handlers.owner_commands import OWNER_COMMANDS
from src.core.emoji import E

logger = logging.getLogger(__name__)


def is_public_command(text: str) -> bool:
    """Публичные команды: др / пары / пары завтра / обнови расписание."""
    return (
        text == "др"
        or text.startswith("др ")
        or text == "пары"
        or text == "пары завтра"
        or text == "обнови расписание"
    )


class Audience(Enum):
    """Кому адресована команда."""
    EVERYONE = auto()
    UNSUBSCRIBE = auto()
    PUBLIC = auto()
    OWNER = auto()


class DenialReason(Enum):
    """Причина отказа — определяет текст."""
    FOREIGN_GROUP = auto()
    NOT_PRIVILEGED = auto()
    OWNER_ONLY = auto()
    PM_ONLY = auto()


DENIAL_TEXTS: dict[DenialReason, str] = {
    DenialReason.FOREIGN_GROUP: (
        f"{E.CROSS} <b>Эта команда доступна в основной беседе или в ЛС "
        "для пользователей из списка группы.</b>"
    ),
    DenialReason.NOT_PRIVILEGED: (
        f"{E.CROSS} <b>Эта команда доступна только избранным пользователям.</b>"
    ),
    DenialReason.OWNER_ONLY: (
        f"{E.CROSS} <b>В доступе отказано</b>\n\n"
        "Эта команда доступна только владельцу бота."
    ),
    DenialReason.PM_ONLY: (
        f"{E.CROSS} Эта команда доступна только в личных сообщениях с ботом."
    ),
}


@dataclass(frozen=True)
class Decision:
    """Результат резолва: разрешено, либо отказ с причиной."""
    allowed: bool
    denial: DenialReason | None = None


_ALLOW = Decision(allowed=True, denial=None)


def classify(normalized_text: str) -> Audience | None:
    """Командное слово → требуемая аудитория. None → это не команда (→ LLM)."""
    if normalized_text in ("help", "команды"):
        return Audience.EVERYONE
    if normalized_text == "отписаться":
        return Audience.UNSUBSCRIBE
    if is_public_command(normalized_text):
        return Audience.PUBLIC
    if normalized_text in OWNER_COMMANDS:
        return Audience.OWNER
    return None


def resolve(audience: Audience, ctx: dict) -> Decision:
    """Чистый резолв доступа. Триггер-гейт групп выполняется ВЫШЕ по потоку."""
    if audience is Audience.EVERYONE:
        return _ALLOW

    if audience is Audience.OWNER:
        return _ALLOW if ctx["is_owner"] else Decision(False, DenialReason.OWNER_ONLY)

    if audience is Audience.UNSUBSCRIBE:
        if ctx["is_group_chat"]:
            return Decision(False, DenialReason.PM_ONLY)
        if ctx["is_owner"] or ctx["is_whitelisted_private"]:
            return _ALLOW
        return Decision(False, DenialReason.NOT_PRIVILEGED)

    # Audience.PUBLIC
    if ctx["is_group_chat"]:
        if ctx["is_group_main"] or ctx["is_owner"]:
            return _ALLOW
        return Decision(False, DenialReason.FOREIGN_GROUP)
    if ctx["is_owner"] or ctx["is_whitelisted_private"]:
        return _ALLOW
    return Decision(False, DenialReason.NOT_PRIVILEGED)


def detect_trigger(message: Message, bot_username: str, bot_id: int) -> bool:
    """Позвали ли бота: упоминание в тексте или реплай на его сообщение.

    Изолированный узел — точка расширения для будущего keyword-trigger.
    None-guard на reply.from_user: реплай от имени канала / анонимного админа
    приходит без from_user.
    """
    text = message.text or ""
    is_mention = any(token == bot_username for token in text.split())
    reply = message.reply_to_message
    is_reply = bool(reply and reply.from_user and reply.from_user.id == bot_id)
    return is_mention or is_reply
