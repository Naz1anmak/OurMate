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

    # Регистрируем обработчики сообщений
    register_handlers(dp)
    logger.info("Обработчики зарегистрированы")

    # Удаляем вебхук и запускаем планировщик
    await bot(DeleteWebhook(drop_pending_updates=True))
    start_birthday_scheduler(bot)
    start_schedule_scheduler(bot)
    start_pinned_schedule_scheduler(bot)
    logger.info("Планировщики запущены")

    # Запускаем поллинг (получение обновлений)
    logger.info("Бот запущен и готов к работе")
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем приложение
    asyncio.run(main())
