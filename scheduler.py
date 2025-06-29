from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
from aiogram import Bot
from pprint import pprint
from config import API_URL, API_HEADERS, TIMEZONE, SEND_HOUR, SEND_MINUTE, MODEL
from utils import load_birthdays, build_mention_list, today_mmdd

def start_scheduler(bot: Bot):
    chat_id, users = load_birthdays()
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    async def job():
        mmdd = today_mmdd(TIMEZONE)
        todays = [u for u in users if u["birthday"] == mmdd]
        if not todays:
            return

        mentions = build_mention_list(todays)
        prompt = (
            f"Ты добавлен в беседу одногруппников в телеграмме. Представь, что ты наш преподаватель Щукин Александр Валентинович, ты вел у нас предметы основные предметы по программированию и алгоритмизации на первом курсе. Ты должен написать креативное дружеское, но немного надменное поздравление с днём рождения студенту {mentions} или студентам, если день рождения у них в один день. Скажи что ты ждешь от них хороших оценок и что они должны учиться лучше, иначе ты поставишь им незачет. Используй поменьше эмодзи в обычном тексте, чтобы не было кринжово. Не будь многословен! Пиши как обычный человек, без красивого форматирования. Мы кстати учимся в Политехе в Санкт-Петербурге по направлению \"Прикладная информатика\"."
        )
        resp = requests.post(API_URL, headers=API_HEADERS, json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Ты — бот-поздравлятор для студентов."},
                {"role": "user",   "content": prompt}
            ]
        })
        text = resp.json()["choices"][0]["message"]["content"]
        pprint(f"Birthday text: {text}, len={len(text)}")
        await bot.send_message(chat_id, text, parse_mode="Markdown")

    # ежедневный запуск в указанное время
    scheduler.add_job(
        job,
        CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE)
    )
    scheduler.start()
