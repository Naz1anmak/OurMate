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

# Файл для фиксации последней даты отправки поздравления
LAST_BIRTHDAY_GREETING_FILE = Path(os.getenv(
    "LAST_BIRTHDAY_GREETING_FILE",
    Path.cwd() / "data" / "cache" / "last_birthday_greeting.txt",
))

# ===== НАСТРОЙКИ РАСПИСАНИЯ =====
# Часовой пояс для планировщика (по умолчанию Москва)
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))

# Время отправки поздравлений (по умолчанию 10:00)
SEND_HOUR = int(os.getenv("SEND_HOUR", 10))
SEND_MINUTE = int(os.getenv("SEND_MINUTE", 0))

# ===== ПРОМПТЫ =====
# Шаблон промпта для обычного чата
PROMPT_TEMPLATE_CHAT = os.getenv("PROMPT_TEMPLATE_CHAT")

# Шаблоны промптов для поздравлений
# Active — основной; Former — для отчисленных. Former по умолчанию наследует Active.
PROMPT_TEMPLATE_BIRTHDAY_ACTIVE = os.getenv("PROMPT_TEMPLATE_BIRTHDAY_ACTIVE")
PROMPT_TEMPLATE_BIRTHDAY_FORMER = os.getenv("PROMPT_TEMPLATE_BIRTHDAY_FORMER", PROMPT_TEMPLATE_BIRTHDAY_ACTIVE)

# ===== НАСТРОЙКИ РАСПИСАНИЯ =====
# Паттерн для файлов расписания (ics)
SCHEDULE_FILES_PATTERN = os.getenv("SCHEDULE_FILES_PATTERN", "data/calendar*.ics")

# Кэш для расписания (после парсинга ics)
SCHEDULE_CACHE_FILE = Path(os.getenv("SCHEDULE_CACHE_FILE", Path.cwd() / "data" / "cache" / "schedule_cache.json"))

# Время отправки расписания
SCHEDULE_SEND_HOUR = int(os.getenv("SCHEDULE_SEND_HOUR", 8))
SCHEDULE_SEND_MINUTE = int(os.getenv("SCHEDULE_SEND_MINUTE", 0))
