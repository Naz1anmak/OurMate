"""Middleware на bot.session: заменяет unicode эмодзи на <tg-emoji> в HTML-тексте.

Telegram Bot API поддерживает кастомный тег <tg-emoji> в HTML parse_mode:

    <tg-emoji emoji-id="5256143829672672750">👤</tg-emoji>

Этот тег заставляет клиент Telegram отрендерить premium-эмодзи вместо unicode.
Работает в любом контексте, где работает parse_mode=HTML.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import (
    EditMessageCaption,
    EditMessageMedia,
    EditMessageText,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.methods.base import Response, TelegramType

from src.core.emoji import ALL_EMOJI

# Для каждого unicode-символа берём первый premium_id из ALL_EMOJI.
_EMOJI_PATTERNS: list[tuple[re.Pattern, str]] = []
_seen_unicode: set[str] = set()
for emoji in ALL_EMOJI:
    if emoji.premium_id and emoji.unicode not in _seen_unicode:
        _seen_unicode.add(emoji.unicode)
        pattern = re.compile(re.escape(emoji.unicode))
        replacement = (
            f'<tg-emoji emoji-id="{emoji.premium_id}">'
            f"{emoji.unicode}"
            f"</tg-emoji>"
        )
        _EMOJI_PATTERNS.append((pattern, replacement))


def inject_tg_emoji(text: str) -> str:
    """Заменяет unicode эмодзи с premium_id на <tg-emoji> теги."""
    if not _EMOJI_PATTERNS or not text:
        return text
    for pattern, replacement in _EMOJI_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _apply_to_text(text: str | None) -> str | None:
    if text is None:
        return None
    return inject_tg_emoji(text)


class PremiumEmojiMiddleware(BaseRequestMiddleware):
    """Заменяет unicode эмодзи на <tg-emoji> теги в исходящих сообщениях.

    Покрытые методы:
      - SendMessage / EditMessageText    → text
      - SendPhoto / EditMessageCaption  → caption
      - EditMessageMedia (InputMedia)    → media.caption
    """

    async def __call__(
        self,
        make_request: Callable[
            [Bot, TelegramMethod[TelegramType]],
            Awaitable[Response[TelegramType]],
        ],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        self._inject_tg_emoji(method)
        return await make_request(bot, method)

    @staticmethod
    def _inject_tg_emoji(method: Any) -> None:
        if isinstance(method, (SendMessage, EditMessageText)):
            if method.text:
                method.text = _apply_to_text(method.text)

        elif isinstance(method, (SendPhoto, EditMessageCaption)):
            if method.caption:
                method.caption = _apply_to_text(method.caption)

        elif isinstance(method, EditMessageMedia):
            media = getattr(method, "media", None)
            if media is not None and getattr(media, "caption", None):
                new_caption = _apply_to_text(media.caption)
                method.media = media.model_copy(update={"caption": new_caption})
