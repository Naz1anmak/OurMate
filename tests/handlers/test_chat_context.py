from datetime import datetime

from src.bot.handlers.chat_context import (
    is_public_command,
    build_llm_messages,
    build_time_context_line,
    _WEEKDAY_RU,
)
from src.config.settings import TIMEZONE


def test_obnovi_raspisanie_is_public():
    assert is_public_command("обнови расписание") is True


def test_existing_public_commands_still_work():
    assert is_public_command("пары") is True
    assert is_public_command("пары завтра") is True
    assert is_public_command("др") is True


def test_time_context_line_has_today_and_weekday():
    now = datetime.now(TIMEZONE)
    line = build_time_context_line()
    assert f"{now:%Y-%m-%d}" in line
    assert _WEEKDAY_RU[now.weekday()] in line


def test_build_llm_messages_injects_time_context_system():
    messages = build_llm_messages(-999_999, "что в субботу?")
    assert messages[0]["role"] == "system"          # персона
    assert messages[1]["role"] == "system"           # контекст времени
    assert "сегодня" in messages[1]["content"].lower()
    assert messages[-1] == {"role": "user", "content": "что в субботу?"}
