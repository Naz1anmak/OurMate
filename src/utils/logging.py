"""Конфигурация логирования: единый формат для stdout и для файла data/logs/bot.log.

Файловый канал нужен для команд владельца `logs` / `full logs` — они читают
этот файл tail-ом. Файл живёт в volume `data/`, поэтому переживает рестарты
контейнера.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FILE_PATH = Path("data/logs/bot.log")
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_FILE_BACKUP_COUNT = 5


class _AiogramSleepFilter(logging.Filter):
    """Глушит шумные сообщения aiogram про 'Sleep for ...' между апдейтами."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "Sleep for" not in record.getMessage()


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure_logging(level: str = "INFO") -> None:
    """Настраивает root-logger: stdout + ротируемый файловый лог.

    Должно вызываться один раз на старте приложения, до создания Bot/Dispatcher.
    """
    formatter = _build_formatter()

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    try:
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        # Файловый лог опционален: если volume не смонтирован — не падаем,
        # stdout-канал останется.
        root.warning("Не удалось открыть %s для логов: %s", LOG_FILE_PATH, exc)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").addFilter(_AiogramSleepFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
