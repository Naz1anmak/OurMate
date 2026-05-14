"""Глобальный error handler и единая функция уведомления владельца.

Используется:
1) global_error_handler — регистрируется через dp.errors.register,
   ловит необработанные исключения в любом хендлере.
2) notify_owner_error — вызывается из except-блоков, где ошибка уже обработана,
   но владельцу всё равно нужно сообщить (LLM недоступен, delivery issue и т.п.).

Формат сообщения один и тот же — чтобы в личке владельца не была каша из разных
шаблонов на каждый тип ошибки.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Update
from aiogram.types.error_event import ErrorEvent

from src.config.settings import OWNER_CHAT_ID

logger = logging.getLogger(__name__)


_EXC_MESSAGE_MAX_LEN = 500
_CONTEXT_MAX_LEN = 500


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_owner_error(
    *,
    exception: Exception,
    tg_id: int | None,
    username: str | None,
    context: str,
    extra: str | None,
    unhandled: bool,
) -> str:
    exc_type = type(exception).__name__
    exc_message = _truncate(str(exception) or "(no message)", _EXC_MESSAGE_MAX_LEN)
    username_info = f" @{html.escape(username)}" if username else ""
    tg_id_str = str(tg_id) if tg_id is not None else "—"
    context_label = f" [{html.escape(context)}]" if context else ""
    title = "🚨 Необработанная ошибка" if unhandled else f"🚨 Ошибка{context_label}"

    lines = [
        f"<b>{title}</b>",
        f"<b>Тип:</b> <code>{html.escape(exc_type)}</code>",
        f"<b>Сообщение:</b> <code>{html.escape(exc_message)}</code>",
        f"<b>Пользователь:</b> <code>{tg_id_str}</code>{username_info}",
    ]
    if extra:
        lines.append(f"<b>Доп:</b> {html.escape(_truncate(extra, _CONTEXT_MAX_LEN))}")
    return "\n".join(lines)


async def notify_owner_error(
    bot: Bot,
    exception: Exception,
    *,
    tg_id: int | None = None,
    username: str | None = None,
    context: str = "",
    extra: str | None = None,
) -> None:
    """Шлёт владельцу единое сообщение об ошибке.

    Args:
        bot: aiogram Bot.
        exception: само исключение.
        tg_id, username: данные пользователя, на действиях которого произошла ошибка.
        context: короткая метка ("LLM недоступен", "Telegram delivery issue", ...).
        extra: произвольный дополнительный контекст (фрагмент ответа, текст запроса и т.п.).
    """
    text = _format_owner_error(
        exception=exception,
        tg_id=tg_id,
        username=username,
        context=context,
        extra=extra,
        unhandled=False,
    )
    try:
        await bot.send_message(OWNER_CHAT_ID, text, parse_mode="HTML")
    except TelegramAPIError as send_exc:
        logger.warning("owner_notify_failed context=%s err=%s", context, send_exc)


def _extract_context(update: Update) -> tuple[int | None, str | None, str]:
    """Извлекает (tg_id, username, update_type) из Update любой структуры."""
    for attr in (
        "message",
        "edited_message",
        "callback_query",
        "inline_query",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
        "pre_checkout_query",
        "shipping_query",
    ):
        value = getattr(update, attr, None)
        if value is not None:
            user = getattr(value, "from_user", None)
            if user is not None:
                return user.id, user.username, attr
    return None, None, "unknown"


async def global_error_handler(event: ErrorEvent, **kwargs: Any) -> bool:
    """Единая точка для необработанных исключений: логирует и шлёт владельцу."""
    exception = event.exception
    update: Update = event.update
    tg_id, username, update_type = _extract_context(update)

    logger.error(
        "unhandled error in %s for tg_id=%s username=%s: %s",
        update_type,
        tg_id,
        username,
        exception,
        exc_info=exception,
    )

    bot: Bot | None = kwargs.get("bot")
    if bot is None:
        return True

    text = _format_owner_error(
        exception=exception,
        tg_id=tg_id,
        username=username,
        context=update_type,
        extra=None,
        unhandled=True,
    )
    try:
        await bot.send_message(OWNER_CHAT_ID, text, parse_mode="HTML")
    except TelegramAPIError as send_exc:
        logger.warning("global_error_handler.owner_notify_failed: %s", send_exc)

    return True
