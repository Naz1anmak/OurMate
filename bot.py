import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.methods import DeleteWebhook

from config import TOKEN
from handlers import register_handlers
from scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

async def main():
    bot = Bot(TOKEN)
    dp = Dispatcher()

    # регистрируем хэндлеры
    register_handlers(dp)

    # удаляем вебхук и запускаем планировщик
    await bot(DeleteWebhook(drop_pending_updates=True))
    start_scheduler(bot)

    # старт поллинга
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())