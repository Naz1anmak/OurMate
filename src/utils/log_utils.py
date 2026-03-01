"""
Утилиты для логирования с временной меткой в заданном часовом поясе.
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config.settings import TIMEZONE, ENV


def log_with_ts(message: str) -> None:
    """Печатает лог: в prod чистое сообщение, в dev — с таймстемпом."""
    is_dev = str(ENV).lower() in ("dev", "development")
    if not is_dev:
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()
        return
    tz = ZoneInfo(TIMEZONE) if isinstance(TIMEZONE, str) else TIMEZONE
    ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    sys.stdout.write(f"{ts} - {message}\n")
    sys.stdout.flush()
