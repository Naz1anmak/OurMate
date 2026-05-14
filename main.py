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
        start_schedule_scheduler(bot)
        start_pinned_schedule_scheduler(bot)
        logger.info("Планировщики запущены")

        logger.info("Бот запущен и готов к работе")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
