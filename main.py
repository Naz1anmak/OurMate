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


async def _delete_webhook_with_retry(bot, max_retries: int = 5) -> None:
    for attempt in range(1, max_retries + 1):
        try:
            await bot(DeleteWebhook(drop_pending_updates=True))
            logger.info("DeleteWebhook успешно выполнен")
            return
        except Exception as exc:
            logger.warning("Ошибка DeleteWebhook (попытка %s/%s): %s", attempt, max_retries, exc)
            if attempt == max_retries:
                logger.error("DeleteWebhook не удалось после всех попыток, продолжаем запуск.")
                return
            await asyncio.sleep(5 * attempt)


async def main() -> None:
    logger.info("Запуск бота...")
    bot, dp = build_bot_and_dispatcher()

    try:
        await _delete_webhook_with_retry(bot)

        start_birthday_scheduler(bot)
        start_schedule_scheduler(bot)
        start_pinned_schedule_scheduler(bot)
        logger.info("Планировщики запущены")

        # Бесконечный polling с backoff: 10с * attempt, максимум 20 минут
        attempt = 1
        while True:
            try:
                logger.info("Бот запущен и готов к работе")
                await dp.start_polling(bot)
                break  # polling завершился штатно
            except Exception as exc:
                delay = min(10 * attempt, 1200)
                logger.warning("Ошибка polling (попытка %s): %s; повтор через %sс", attempt, exc, delay)
                await asyncio.sleep(delay)
                attempt += 1
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
