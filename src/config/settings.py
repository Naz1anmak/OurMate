"""
Модуль конфигурации приложения.
Содержит все настройки, загружаемые из переменных окружения.
"""

from dotenv import load_dotenv
import os
from pathlib import Path
from zoneinfo import ZoneInfo

# Загружаем переменные окружения из файла .env
load_dotenv()

# ===== TELEGRAM НАСТРОЙКИ =====
# Токен бота из BotFather
TOKEN = os.getenv("BOT_TOKEN")

# ID чата владельца для личных уведомлений
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID"))

# ID группы для отправки поздравлений
CHAT_ID = int(os.getenv("CHAT_ID"))

# ===== LLM API НАСТРОЙКИ =====
# URL API для работы с языковой моделью
API_URL = "https://api.intelligence.io.solutions/api/v1/chat/completions"

# Модель для использования (например, "deepseek-ai/DeepSeek-R1-0528")
MODEL = os.getenv("MODEL")

# Заголовки для API запросов
API_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.getenv('LLM_API_KEY')}"
}

# ===== НАСТРОЙКИ ДНЕЙ РОЖДЕНИЯ =====
# Путь к файлу с данными о днях рождения
# По умолчанию ищем файл birthdays.json в папке data относительно корня проекта
BIRTHDAYS_FILE = Path(os.getenv("BIRTHDAYS_FILE", Path.cwd() / "data" / "birthdays.json"))

# ===== НАСТРОЙКИ РАСПИСАНИЯ =====
# Часовой пояс для планировщика (по умолчанию Москва)
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))

# Время отправки поздравлений (по умолчанию 10:00)
SEND_HOUR = int(os.getenv("SEND_HOUR", 10))
SEND_MINUTE = int(os.getenv("SEND_MINUTE", 0))

# ===== ПРОМПТЫ =====
# Шаблон промпта для обычного чата
PROMPT_TEMPLATE_CHAT = os.getenv("PROMPT_TEMPLATE_CHAT")

# Шаблон промпта для поздравлений
PROMPT_TEMPLATE_BIRTHDAY = os.getenv("PROMPT_TEMPLATE_BIRTHDAY")
