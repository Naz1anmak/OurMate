from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path
from zoneinfo import ZoneInfo

# Telegram
TOKEN           = os.getenv("BOT_TOKEN")
OWNER_CHAT_ID   = int(os.getenv("OWNER_CHAT_ID"))  # для личных уведомлений
CHAT_ID         = int(os.getenv("CHAT_ID")) # Где слать поздравления

# API LLM
API_URL = "https://api.intelligence.io.solutions/api/v1/chat/completions"
MODEL        = os.getenv("MODEL") # "deepseek-ai/DeepSeek-R1-0528"
API_HEADERS  = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.getenv('LLM_API_KEY')}"
}

# Путь к файлу с днями рождения
BIRTHDAYS_FILE = Path(os.getenv("BIRTHDAYS_FILE", Path(__file__).parent/"birthdays.json"))

# Расписание
TIMEZONE     = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
SEND_HOUR    = int(os.getenv("SEND_HOUR", 10))
SEND_MINUTE  = int(os.getenv("SEND_MINUTE", 0))

# Промпты
PROMPT_TEMPLATE_CHAT = os.getenv("PROMPT_TEMPLATE_CHAT")
PROMPT_TEMPLATE_BIRTHDAY = os.getenv("PROMPT_TEMPLATE_BIRTHDAY")