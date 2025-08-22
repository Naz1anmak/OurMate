"""
Главный файл приложения OurMate Bot.
Точка входа для запуска Telegram бота.
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.methods import DeleteWebhook

from src.config.settings import TOKEN
from src.bot.handlers import register_handlers
from src.bot.scheduler.birthday_scheduler import start_scheduler

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

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
    start_scheduler(bot)
    logger.info("Планировщик запущен")

    # Запускаем поллинг (получение обновлений)
    logger.info("Бот запущен и готов к работе")
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем приложение
    asyncio.run(main())
