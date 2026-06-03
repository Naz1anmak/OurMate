"""Сборка Bot и Dispatcher: создание, middleware, регистрация хэндлеров."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession

from src.config.settings import TOKEN, TELEGRAM_PROXY_URL, TELEGRAM_PROXY_ENABLED
from src.bot.handlers import register_handlers
from src.bot.handlers.errors import global_error_handler
from src.bot.middlewares.emoji import PremiumEmojiMiddleware
from src.bot.handlers.reminder_callbacks import on_reminder_callback
from src.bot.handlers.ping_callbacks import on_ping_callback

logger = logging.getLogger(__name__)


def build_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    """Создаёт Bot (с прокси, если задан) и Dispatcher с подключёнными хэндлерами/middleware."""
    if TELEGRAM_PROXY_ENABLED and TELEGRAM_PROXY_URL:
        proxy_url = TELEGRAM_PROXY_URL.strip()
        if not proxy_url.startswith("socks5://"):
            proxy_url = f"socks5://{proxy_url}"
        logger.info("Using proxy: %s", proxy_url)
        session = AiohttpSession(proxy=proxy_url)
        bot = Bot(TOKEN, session=session)
    else:
        bot = Bot(TOKEN)

    bot.session.middleware(PremiumEmojiMiddleware())

    dp = Dispatcher()
    register_handlers(dp)
    dp.callback_query.register(on_reminder_callback, F.data.startswith("rem:"))
    dp.callback_query.register(on_ping_callback, F.data.startswith("ping:"))
    dp.errors.register(global_error_handler)
    logger.info("Обработчики зарегистрированы")
    return bot, dp
