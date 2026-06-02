from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.bot.handlers.chat_commands import handle_public_commands

TZ = ZoneInfo("Europe/Moscow")


def _msg(text="обнови расписание", chat_id=-100123):
    m = MagicMock()
    m.text = text
    m.from_user.id = 42
    m.from_user.username = "user"
    m.from_user.full_name = "Test User"
    m.chat.type = "supergroup"
    m.chat.id = chat_id
    m.answer = AsyncMock(return_value=MagicMock(message_id=999))
    m.bot = AsyncMock()
    m.bot.edit_message_text = AsyncMock()
    return m


@pytest.fixture
def ctx_allowed():
    return {
        "normalized_text": "обнови расписание",
        "text_for_commands": "обнови расписание",
        "is_group_chat": True,
    }


@pytest.mark.asyncio
async def test_obnovi_calls_force_refresh_and_pinned_update_now(monkeypatch, ctx_allowed):
    refresher = AsyncMock()
    refresher.force_refresh = AsyncMock(return_value=MagicMock(
        updated_groups=["40001"], failed_groups=[], diff_message=None,
    ))
    pinned = AsyncMock()
    pinned.update_now = AsyncMock()

    monkeypatch.setattr("src.bot.handlers.chat_commands.schedule_refresher", refresher)
    monkeypatch.setattr("src.bot.handlers.chat_commands.pinned_scheduler", pinned)

    m = _msg()
    handled = await handle_public_commands(m, ctx_allowed)
    assert handled is True
    refresher.force_refresh.assert_called_once()
    pinned.update_now.assert_called_once()


@pytest.mark.asyncio
async def test_obnovi_replies_no_change_when_no_diff(monkeypatch, ctx_allowed):
    refresher = AsyncMock()
    refresher.force_refresh = AsyncMock(return_value=MagicMock(
        updated_groups=["40001"], failed_groups=[], diff_message=None,
    ))
    pinned = AsyncMock()
    monkeypatch.setattr("src.bot.handlers.chat_commands.schedule_refresher", refresher)
    monkeypatch.setattr("src.bot.handlers.chat_commands.pinned_scheduler", pinned)

    m = _msg()
    await handle_public_commands(m, ctx_allowed)
    # Найти финальный edit_message_text вызов
    edit_calls = m.bot.edit_message_text.call_args_list
    assert any("не изменилось" in str(c) for c in edit_calls)


@pytest.mark.asyncio
async def test_obnovi_replies_full_fail_with_link(monkeypatch, ctx_allowed):
    refresher = AsyncMock()
    refresher.force_refresh = AsyncMock(return_value=MagicMock(
        updated_groups=[], failed_groups=["40001"], diff_message=None,
    ))
    refresher.client = MagicMock()
    refresher.client.public_url = MagicMock(return_value="https://schedule.example/faculty/125/groups/99000?date=2026-5-25")
    refresher.group_ids = {"40001": 99000}
    monkeypatch.setattr("src.bot.handlers.chat_commands.schedule_refresher", refresher)

    m = _msg()
    await handle_public_commands(m, ctx_allowed)
    edit_calls = m.bot.edit_message_text.call_args_list
    text = " ".join(str(c) for c in edit_calls)
    assert "недоступно" in text
    assert "schedule.example" in text
