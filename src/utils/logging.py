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


# Типы ошибок поллинга, которые aiogram переживает сам: он ретраит и
# восстанавливает соединение. Каждую ночь их приносит окно техобслуживания
# Telegram, поэтому на уровне ERROR они только маскируют настоящие проблемы.
TRANSIENT_POLLING_ERRORS = (
    "TelegramRetryAfter",
    "TelegramServerError",
    "TelegramNetworkError",
)


class _AiogramTransientFilter(logging.Filter):
    """Глушит предсказуемый шум aiogram: 'Sleep for ...' между апдейтами и
    транзиентные ошибки поллинга.

    Транзиентные ошибки не выбрасываются насовсем, а понижаются до DEBUG:
    при `LOG_LEVEL=INFO` (прод) они не видны, при `LOG_LEVEL=DEBUG` остаются
    доступными для разбора инцидента. Всё остальное, включая
    `TelegramUnauthorizedError`, проходит нетронутым.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "Sleep for" in message:
            return False
        if "Failed to fetch updates" in message and any(
            err in message for err in TRANSIENT_POLLING_ERRORS
        ):
            if not logging.getLogger().isEnabledFor(logging.DEBUG):
                return False
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


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
    logging.getLogger("aiogram.dispatcher").addFilter(_AiogramTransientFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
