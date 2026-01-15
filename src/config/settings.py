"""
Модуль конфигурации приложения.
Содержит все настройки, загружаемые из переменных окружения.
"""
from dotenv import load_dotenv
import os
from pathlib import Path
from zoneinfo import ZoneInfo

def _get_env(name: str, default=None, cast=None, log_default: bool = False):
    """Возвращает значение переменной окружения с опциональным кастом и логом по умолчанию."""
    val = os.getenv(name)
    if val is None:
        if log_default:
            print(f"[CONFIG] {name} не задан, используем значение по умолчанию: {default}")
        val = default
    if cast and val is not None:
        return cast(val)
    return val

# Загружаем переменные окружения из файла .env
load_dotenv()

# Режим окружения
ENV = _get_env("ENV", "dev", log_default=True)

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
BIRTHDAYS_FILE = Path(_get_env("BIRTHDAYS_FILE", Path.cwd() / "data" / "birthdays.json", log_default=True))

# Файл для фиксации последней даты отправки поздравления
LAST_BIRTHDAY_GREETING_FILE = Path(
    _get_env(
        "LAST_BIRTHDAY_GREETING_FILE",
        Path.cwd() / "data" / "cache" / "last_birthday_greeting.txt",
        log_default=True,
    )
)

# ===== НАСТРОЙКИ РАСПИСАНИЯ =====
# Часовой пояс для планировщика (по умолчанию Москва)
TIMEZONE = ZoneInfo(_get_env("TIMEZONE", "Europe/Moscow", log_default=True))

# Время отправки поздравлений (по умолчанию 10:00)
SEND_HOUR = int(_get_env("SEND_HOUR", 10, log_default=True))
SEND_MINUTE = int(_get_env("SEND_MINUTE", 0, log_default=True))

# ===== ПРОМПТЫ =====
# Шаблон промпта для обычного чата
PROMPT_TEMPLATE_CHAT = _get_env("PROMPT_TEMPLATE_CHAT", "", log_default=True)

# Шаблоны промптов для поздравлений
# Active — основной; Former — для отчисленных. Former по умолчанию наследует Active.
PROMPT_TEMPLATE_BIRTHDAY_ACTIVE = _get_env("PROMPT_TEMPLATE_BIRTHDAY_ACTIVE", "", log_default=True)
PROMPT_TEMPLATE_BIRTHDAY_FORMER = _get_env(
    "PROMPT_TEMPLATE_BIRTHDAY_FORMER", PROMPT_TEMPLATE_BIRTHDAY_ACTIVE, log_default=True
)

# ===== НАСТРОЙКИ РАСПИСАНИЯ =====
# Паттерн для файлов расписания (ics)
SCHEDULE_FILES_PATTERN = _get_env("SCHEDULE_FILES_PATTERN", "data/calendar*.ics", log_default=True)

# Кэш для расписания (после парсинга ics)
SCHEDULE_CACHE_FILE = Path(
    _get_env("SCHEDULE_CACHE_FILE", Path.cwd() / "data" / "cache" / "schedule_cache.json", log_default=True)
)

# Время отправки расписания
SCHEDULE_SEND_HOUR = int(_get_env("SCHEDULE_SEND_HOUR", 8, log_default=True))
SCHEDULE_SEND_MINUTE = int(_get_env("SCHEDULE_SEND_MINUTE", 0, log_default=True))
