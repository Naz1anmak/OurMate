"""Тесты фильтра транзиентных ошибок aiogram (src/utils/logging.py)."""
import logging

import pytest

from src.utils.logging import _AiogramTransientFilter


def _record(level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="aiogram.dispatcher",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


TRANSIENT = [
    "Failed to fetch updates - TelegramRetryAfter: Telegram server says - "
    "Flood control exceeded on method 'GetUpdates'. Retry in 5 seconds.",
    "Failed to fetch updates - TelegramServerError: Telegram server says - Bad Gateway",
    "Failed to fetch updates - TelegramNetworkError: HTTP Client says - Request timeout error",
]


@pytest.mark.parametrize("msg", TRANSIENT)
def test_transient_dropped_at_info(msg, monkeypatch):
    """При INFO транзиентные ошибки поллинга не проходят в хендлеры."""
    logging.getLogger().setLevel(logging.INFO)
    rec = _record(logging.ERROR, msg)
    assert _AiogramTransientFilter().filter(rec) is False


@pytest.mark.parametrize("msg", TRANSIENT)
def test_transient_downgraded_at_debug(msg):
    """При DEBUG они проходят, но с уровнем DEBUG, а не ERROR."""
    logging.getLogger().setLevel(logging.DEBUG)
    rec = _record(logging.ERROR, msg)
    try:
        assert _AiogramTransientFilter().filter(rec) is True
        assert rec.levelno == logging.DEBUG
        assert rec.levelname == "DEBUG"
    finally:
        logging.getLogger().setLevel(logging.INFO)


def test_sleep_noise_still_dropped():
    """Старое поведение сохранено: 'Sleep for' глушится всегда."""
    logging.getLogger().setLevel(logging.DEBUG)
    try:
        rec = _record(logging.INFO, "Sleep for 1.0 seconds")
        assert _AiogramTransientFilter().filter(rec) is False
    finally:
        logging.getLogger().setLevel(logging.INFO)


def test_real_error_untouched():
    """Настоящие ошибки не глушатся и не понижаются."""
    logging.getLogger().setLevel(logging.INFO)
    rec = _record(
        logging.ERROR,
        "Failed to fetch updates - TelegramUnauthorizedError: Unauthorized",
    )
    assert _AiogramTransientFilter().filter(rec) is True
    assert rec.levelno == logging.ERROR


def test_unrelated_error_untouched():
    logging.getLogger().setLevel(logging.INFO)
    rec = _record(logging.ERROR, "Cause exception while process update")
    assert _AiogramTransientFilter().filter(rec) is True
    assert rec.levelno == logging.ERROR
