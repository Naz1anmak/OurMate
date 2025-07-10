from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
import requests
from aiogram import Bot
from config import (API_URL, API_HEADERS, TIMEZONE, 
                    SEND_HOUR, SEND_MINUTE, MODEL, CHAT_ID, 
                    OWNER_CHAT_ID, PROMPT_TEMPLATE_BIRTHDAY)
from utils import (load_birthdays, build_mention_list, 
                   today_mmdd, get_next_birthday)

 # Для подписей месяца
MONTH_NAMES = {
    1:  "января",   2:  "февраля", 3:  "марта",
    4:  "апреля",   5:  "мая",     6:  "июня",
    7:  "июля",     8:  "августа", 9:  "сентября",
    10: "октября", 11: "ноября",  12: "декабря"
}

def start_scheduler(bot: Bot):
    users = load_birthdays()

    async def notify_next():
        """Единоразовое уведомление о ближайших ДР при старте."""
        # 1) найдём ближайшую дату
        next_user = get_next_birthday(users, today_mmdd(TIMEZONE))
        if not next_user:
            return
        # 2) вытащим дату
        month, day = map(int, next_user["birthday"].split("-"))
        date_key = f"{month:02d}-{day:02d}"
        # 3) всех пользователей на этот день
        group = [u for u in users if u["birthday"] == date_key]
        mentions = build_mention_list(group)
        # 4) отформатируем дату
        formatted_bd = f"{day} {MONTH_NAMES[month]}"
        # 5) отправим в ЛС
        await bot.send_message(
            OWNER_CHAT_ID,
            f"Следующий день рождения — {formatted_bd}:\n"
            f"{mentions}"
        )

    async def job():
        """Поздравление сегодня + уведомление о следующих ДР."""
        today = today_mmdd(TIMEZONE)
        todays = [u for u in users if u["birthday"] == today]
        if not todays:
            return

        mentions = build_mention_list(todays)
        prompt = PROMPT_TEMPLATE_BIRTHDAY.format(mentions=mentions)
        resp = requests.post(API_URL, headers=API_HEADERS, json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Ты — бот-поздравлятор для студентов."},
                {"role": "user",   "content": prompt}
            ]
        })
        # Отделяем мысли
        full = resp.json()["choices"][0]["message"]["content"]
        if "</think>\n" in full:
            text = full.split("</think>\n")[-1].strip()
        else:
            text = full.strip()
        # safe_text = escape_md(text)
        await bot.send_message(CHAT_ID, text)

        # Уведомляем о следующем ДР
        next_user = get_next_birthday(users, today)
        if not next_user:
            return
        month, day = map(int, next_user["birthday"].split("-"))
        date_key = next_user["birthday"]
        group = [u for u in users if u["birthday"] == date_key]
        mentions = build_mention_list(group)
        formatted_bd = f"{day} {MONTH_NAMES[month]}"

        await bot.send_message(
            OWNER_CHAT_ID,
            f"Следующий день рождения — {formatted_bd}:\n"
            f"{mentions}"
        )

    # ========== запуск при старте ==========
    loop = asyncio.get_event_loop()
    loop.create_task(notify_next())  # уведомим о ближайшем ДР
    loop.create_task(job())          # сразу же проверим и поздравим сегодняшних

    # ========== ежедневный Cron ==========
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        job,
        CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE)
    )
    scheduler.start()