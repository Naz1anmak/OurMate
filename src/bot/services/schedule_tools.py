"""Тул-функции расписания для tool use + их JSON-схемы."""
import logging
from datetime import date, datetime
from typing import Optional, Tuple, Union

from src.bot.services.llm_tools import ToolSpec
from src.bot.services.schedule_service import ScheduleEvent, schedule_service
from src.config.settings import RUZ_WEEKS_AHEAD, TIMEZONE

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = {0: "понедельник", 1: "вторник", 2: "среда", 3: "четверг",
                 4: "пятница", 5: "суббота", 6: "воскресенье"}

DEFAULT_MAX_DAYS = (RUZ_WEEKS_AHEAD + 1) * 7


def validate_date_range(
    date_from: str, date_to: str, *, max_days: int = DEFAULT_MAX_DAYS
) -> Tuple[bool, Union[Tuple[date, date], dict]]:
    """Парсит и валидирует ISO-диапазон. (True, (from, to)) или (False, {"error","hint"})."""
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except (ValueError, TypeError):
        return False, {"error": "bad_range", "hint": "Даты должны быть в формате YYYY-MM-DD."}
    if d_from > d_to:
        return False, {"error": "bad_range", "hint": "date_from позже date_to."}
    if (d_to - d_from).days > max_days:
        return False, {"error": "bad_range", "hint": f"Диапазон больше {max_days} дней."}
    return True, (d_from, d_to)
