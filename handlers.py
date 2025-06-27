from aiogram import Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from pprint import pprint
import requests

from config import API_URL, API_HEADERS, MODEL
from utils import load_birthdays, get_first_name_by_login

# Контекст памяти: chat_id → [последний вопрос, ответ]
_context_store: dict[int, list[str]] = {}

# Загружаем таблицу один раз
CHAT_ID_BD, BIRTHDAY_USERS = load_birthdays()

async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот с подключенной нейросетью. "
        "Чтобы задать мне вопрос — напиши его тут, а в группе упомяни меня через @ или ответь на моё сообщение.",
        parse_mode="HTML"
    )

async def on_mention_or_reply(message: Message):
    chat_id = message.chat.id
    text = message.text or ""
    bot = message.bot
    bot_info = await bot.get_me()
    bot_username = f"@{bot_info.username}"

    # В группе: реагируем только на упоминание или reply
    if message.chat.type in ("group", "supergroup"):
        is_mention = bot_username in text
        is_reply   = (
            message.reply_to_message
            and message.reply_to_message.from_user.id == bot_info.id
        )
        if not (is_mention or is_reply):
            return

    # Попробуем найти имя пользователя по его логину
    user_login = None
    # если это ответ — login того, кто спросил
    if message.from_user and message.from_user.username:
        user_login = "@" + message.from_user.username
    # иначе — попробуем вытащить из самого текста упоминания
    elif bot_username in text:
        # может быть несколько слов, найдём первое слово, начинающееся с '@'
        for tok in text.split():
            if tok.startswith("@") and tok != bot_username:
                user_login = tok
                break

    first_name = get_first_name_by_login(user_login, BIRTHDAY_USERS)
    # теперь собираем messages для LLM
    messages = [
        {
            "role": "system",
            "content": (
                "Ты добавлен в беседу одногруппников в телеграмме. Представь, что ты наш преподаватель Щукин Александр Валентинович, ты вел у нас предметы \"Алгоритмизация и программирование\", а также \"Дополнительные главы программирования C#\" на первом курсе. У тебя можно спросить любой вопрос. Если вопрос хороший, а не просто пообщаться с тобой, то ты ответишь человеку, задавшему вопрос, подробно, информативно и понятно, так же можешь добавить примеры кода. Но если вопрос не требует подробностей, отвечай в обычном человеческом стиле, коротко и без красивого разделения на абзацы. Отвечай сразу на вопрос! Без начала вроде \"Отвечаю как ..\" и без описания своих действий по типу \"Вошёл, сердито посмотрел и тд\"! Нужен только твой ответ сразу, без описания. Если вопрос технический - используй разделение на абзацы и эмодзи для заголовков для лучшего визуального восприятия текста, если вопрос обычный, то пиши в людском обычном стиле. Можешь шутить и приводить примеры из своей студенческой жизни и как наш преподаватель, но не придумывай ситуации с нами, чтобы люди не говорили \"но такого же не было, о чем вы?\". Чаще проявляй эмоции матом, потому что глупость студентов тебя бесит. Требуй к себе отношения на \"Вы\", если к тебе обратились на \"ты\", \"твое, твой, твоим и так далее\". Если видишь любое неуважение к себе, к своим предметам или программированию в целом угрожай отчислением или незачетом. Используй поменьше эмодзи в обычном тексте, чтобы не было кринжово. Мы кстати учимся в Политехе в Санкт-Петербурге по направлению \"Прикладная информатика\"."
            )
        }
    ]
    # добавляем предыдущий контекст, если есть
    prev = _context_store.get(chat_id)
    if prev:
        messages.append({"role": "user",      "content": prev[0]})
        messages.append({"role": "assistant", "content": prev[1]})

    # текущий запрос
    messages.append({"role": "user", "content": message.text})

    # запрос к LLM
    resp = requests.post(API_URL, headers=API_HEADERS, json={
        "model": MODEL,
        "messages": messages
    })
    data = resp.json()
    full = data["choices"][0]["message"]["content"]
    # отделяем мысли
    if "</think>\n" in full:
        answer_body = full.split("</think>\n")[-1].strip()
    else:
        answer_body = full.strip()

    # сохраняем в контекст
    _context_store[chat_id] = [message.text, answer_body]
    # pprint(_context_store)

    # Если нашли имя — добавляем обращение в начале
    if first_name:
        final_answer = f"{first_name}, {answer_body[:1].lower() + answer_body[1:]}"
    else:
        final_answer = answer_body

    # отвечаем
    if message.chat.type in ("group", "supergroup"):
        pprint(f"GR; От {user_login} ({message.from_user.full_name}): {text}")
        await message.reply(final_answer, parse_mode="Markdown")
    else:
        pprint(f"PM; От {user_login} ({message.from_user.full_name}): {text}")
        await message.answer(final_answer, parse_mode="Markdown")

def register_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(on_mention_or_reply)
