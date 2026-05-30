"""Точка входа OurMate Bot."""
import asyncio
import logging
import os

# Конфигурируем логирование до прочих импортов, чтобы ранние сообщения (парсинг расписания)
# тоже шли в единый формат.
from src.utils.logging import configure_logging

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

from aiogram.methods import DeleteWebhook

from src.bot.setup import build_bot_and_dispatcher
from src.bot.scheduler.birthday_scheduler import start_birthday_scheduler
from src.bot.scheduler.schedule_scheduler import start_schedule_scheduler
from src.bot.scheduler.pinned_schedule_scheduler import start_pinned_schedule_scheduler
from src.bot.scheduler.schedule_auto_refresh_scheduler import start_schedule_auto_refresh_scheduler
from src.bot.services.ruz_client import RuzClient
from src.bot.services.schedule_refresher import ScheduleRefresher
from src.bot.services.schedule_service import schedule_service
from src.bot.handlers import chat_commands as chat_commands_module
from src.bot.handlers import chat_group as chat_group_module
from src.bot.handlers import chat_pm as chat_pm_module
from src.bot.services.schedule_tools import build_schedule_registry
from src.config.settings import (
    RUZ_BASE_URL, RUZ_FACULTY_ID, RUZ_HTTP_TIMEOUT,
    RUZ_WEEKS_AHEAD, RUZ_LAZY_TTL_MIN, RUZ_GROUP_IDS,
    SCHEDULE_AUTO_UPDATE_ENABLED,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Запуск бота...")
    bot, dp = build_bot_and_dispatcher()

    try:
        try:
            await bot(DeleteWebhook(drop_pending_updates=True))
            logger.info("DeleteWebhook успешно выполнен")
        except Exception as exc:
            logger.warning("DeleteWebhook не выполнен, продолжаем запуск: %s", exc)

        start_birthday_scheduler(bot)
        schedule_scheduler_instance = start_schedule_scheduler(bot)
        pinned_scheduler_instance = start_pinned_schedule_scheduler(bot)
        auto_refresh_instance = start_schedule_auto_refresh_scheduler(bot)

        refresher = None
        if SCHEDULE_AUTO_UPDATE_ENABLED:
            ruz_client = RuzClient(
                base_url=RUZ_BASE_URL,
                faculty_id=RUZ_FACULTY_ID,
                timeout=RUZ_HTTP_TIMEOUT,
            )
            refresher = ScheduleRefresher(
                client=ruz_client,
                schedule_service=schedule_service,
                group_ids=RUZ_GROUP_IDS,
                weeks_ahead=RUZ_WEEKS_AHEAD,
                lazy_ttl_min=RUZ_LAZY_TTL_MIN,
            )
            schedule_scheduler_instance.refresher = refresher
            pinned_scheduler_instance.refresher = refresher
            auto_refresh_instance.refresher = refresher
            auto_refresh_instance.pinned_scheduler = pinned_scheduler_instance
            chat_commands_module.schedule_refresher = refresher
            chat_commands_module.pinned_scheduler = pinned_scheduler_instance
            logger.info("Автообновление расписания включено, группы: %s", list(RUZ_GROUP_IDS))
        else:
            logger.info("Автообновление расписания выключено (SCHEDULE_AUTO_UPDATE_ENABLED=false)")

        # Общий реестр тулов для NL-вопросов (работает и без refresher — тулы берут глобальный schedule_service).
        tool_registry = build_schedule_registry(refresher=refresher)
        from src.bot.services.web_search_tool import build_web_search_registry
        from src.config.settings import TAVILY_API_KEY
        if TAVILY_API_KEY:
            ws_reg = build_web_search_registry()
            ws_spec = ws_reg.get("web_search")
            tool_registry.register("web_search", ws_spec)
            logger.info("Тул web_search подключён (Tavily)")
        else:
            logger.info("web_search выключен (TAVILY_API_KEY не задан)")
        chat_group_module.tool_registry = tool_registry
        chat_pm_module.tool_registry = tool_registry
        logger.info("Реестр тулов подключён (refresh: %s)", "вкл" if refresher else "выкл")

        logger.info("Планировщики запущены")

        logger.info("Бот запущен и готов к работе")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
