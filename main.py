"""
Главный файл приложения OurMate Bot.
Точка входа для запуска Telegram бота.
"""
import os
import asyncio
import logging

# Настраиваем логирование до импортов, чтобы ранние сообщения (парсинг расписания) не терялись
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Шумные события aiogram подавляем всегда
logging.getLogger("aiogram.event").setLevel(logging.WARNING)

# Приглушаем только сообщения aiogram.dispatcher про "Sleep for ..."
class _AiogramSleepFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        msg = record.getMessage()
        return "Sleep for" not in msg

logging.getLogger("aiogram.dispatcher").addFilter(_AiogramSleepFilter())

from aiogram import Bot, Dispatcher
from aiogram.methods import DeleteWebhook

from src.config.settings import TOKEN
from src.bot.handlers import register_handlers
from src.bot.scheduler.birthday_scheduler import start_birthday_scheduler
from src.bot.scheduler.schedule_scheduler import start_schedule_scheduler
from src.bot.scheduler.pinned_schedule_scheduler import start_pinned_schedule_scheduler

logger = logging.getLogger(__name__)

async def main():
    """
    Главная функция приложения.
    Инициализирует и запускает бота.
    """
    logger.info("Запуск OurMate Bot...")
    
    # Создаем экземпляры бота и диспетчера
    bot = Bot(TOKEN)
    dp = Dispatcher()

    try:
        # Регистрируем обработчики сообщений
        register_handlers(dp)
        logger.info("Обработчики зарегистрированы")

        # Retry для DeleteWebhook
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                await bot(DeleteWebhook(drop_pending_updates=True))
                logger.info("DeleteWebhook успешно выполнен")
                break
            except Exception as exc:
                logger.warning(f"Ошибка DeleteWebhook (попытка {attempt}/{max_retries}): {exc}")
                if attempt == max_retries:
                    logger.error("DeleteWebhook не удалось после всех попыток, продолжаем запуск.")
                else:
                    await asyncio.sleep(5 * attempt)

        start_birthday_scheduler(bot)
        start_schedule_scheduler(bot)
        start_pinned_schedule_scheduler(bot)
        logger.info("Планировщики запущены")

        # Бесконечный polling с backoff: задержка растет на 10 секунд каждую попытку, максимум 20 минут
        attempt = 1
        while True:
            try:
                logger.info("Бот запущен и готов к работе")
                await dp.start_polling(bot)
                break  # polling завершился штатно
            except Exception as exc:
                logger.warning(f"Ошибка polling (попытка {attempt}): {exc}")
                delay = min(10 * attempt, 1200)  # максимум 20 минут
                logger.info(f"Следующая попытка polling через {delay} секунд")
                await asyncio.sleep(delay)
                attempt += 1
    finally:
        # Корректно закрываем HTTP-сессию, даже при Ctrl+C
        await bot.session.close()

if __name__ == "__main__":
    # Запускаем приложение
    asyncio.run(main())
