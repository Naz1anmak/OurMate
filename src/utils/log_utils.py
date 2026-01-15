"""
Утилиты для логирования с временной меткой в заданном часовом поясе.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.config.settings import TIMEZONE, ENV


def log_with_ts(message: str) -> None:
    """Печатает лог с таймстемпом в часовом поясе из настроек."""
    if str(ENV).lower() == "prod":
        print(message)
        return
    tz = ZoneInfo(TIMEZONE) if isinstance(TIMEZONE, str) else TIMEZONE
    ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    print(f"{ts} - {message}")
