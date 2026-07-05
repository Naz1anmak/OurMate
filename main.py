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
from src.bot.services.schedule_client import ScheduleClient
from src.bot.services.schedule_refresher import ScheduleRefresher
from src.bot.services.schedule_service import schedule_service
from src.bot.handlers import chat_commands as chat_commands_module
from src.bot.handlers import chat_group as chat_group_module
from src.bot.handlers import chat_pm as chat_pm_module
from src.bot.services.schedule_tools import build_schedule_registry
from src.bot.scheduler.reminder_scheduler import start_reminder_scheduler
from src.bot.services.reminder_tools import build_reminder_registry
from src.bot.handlers import reminder_callbacks as reminder_callbacks_module
from src.bot.services.usage_limit_store import usage_limit_store
from src.bot.services.ping_store import ping_store
from src.bot.services.notes_store import notes_store
from src.bot.services.notes_tools import build_notes_registry
from src.config.settings import (
    SCHEDULE_API_BASE_URL, SCHEDULE_API_FACULTY_ID, SCHEDULE_API_HTTP_TIMEOUT,
    SCHEDULE_API_WEEKS_AHEAD, SCHEDULE_API_LAZY_TTL_MIN, SCHEDULE_API_GROUP_IDS,
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
        reminder_scheduler_instance = start_reminder_scheduler(bot)
        await reminder_scheduler_instance.start()
        reminder_callbacks_module.scheduler = reminder_scheduler_instance

        await usage_limit_store.init()
        removed = await usage_limit_store.cleanup_old()
        logger.info("usage-лимиты: стор готов, подметено старых строк: %s", removed)

        await ping_store.init()
        logger.info("пинг-лист: стор готов")

        await notes_store.init()
        removed_notes = await notes_store.cleanup_old()
        logger.info("списки: стор готов, подметено старых: %s", removed_notes)

        refresher = None
        if SCHEDULE_AUTO_UPDATE_ENABLED:
            schedule_client = ScheduleClient(
                base_url=SCHEDULE_API_BASE_URL,
                faculty_id=SCHEDULE_API_FACULTY_ID,
                timeout=SCHEDULE_API_HTTP_TIMEOUT,
            )
            refresher = ScheduleRefresher(
                client=schedule_client,
                schedule_service=schedule_service,
                group_ids=SCHEDULE_API_GROUP_IDS,
                weeks_ahead=SCHEDULE_API_WEEKS_AHEAD,
                lazy_ttl_min=SCHEDULE_API_LAZY_TTL_MIN,
            )
            schedule_scheduler_instance.refresher = refresher
            pinned_scheduler_instance.refresher = refresher
            auto_refresh_instance.refresher = refresher
            auto_refresh_instance.pinned_scheduler = pinned_scheduler_instance
            chat_commands_module.schedule_refresher = refresher
            chat_commands_module.pinned_scheduler = pinned_scheduler_instance
            logger.info("Автообновление расписания включено, группы: %s", list(SCHEDULE_API_GROUP_IDS))
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
        for name, spec in build_reminder_registry(scheduler=reminder_scheduler_instance).items():
            tool_registry.register(name, spec)
        logger.info("Тулы напоминаний подключены")
        for name, spec in build_notes_registry().items():
            tool_registry.register(name, spec)
        logger.info("Тулы списков подключены")
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
