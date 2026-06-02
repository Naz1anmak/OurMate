from unittest.mock import AsyncMock
import pytest

import src.bot.scheduler.birthday_scheduler as bsched
from src.bot.scheduler.birthday_scheduler import BirthdayScheduler
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendChatAction

_M = SendChatAction(chat_id=1, action="typing")


@pytest.fixture
def no_real_sleep(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(bsched.asyncio, "sleep", fake_sleep)
    return sleeps


async def test_throttled_call_sleeps_then_returns(no_real_sleep):
    sched = BirthdayScheduler(AsyncMock())
    sched._probe_delay = 0.1
    call = AsyncMock(return_value="ok")

    result = await sched._throttled_call(call)

    assert result == "ok"
    assert no_real_sleep == [0.1]          # одна пауза перед вызовом
    assert call.await_count == 1


async def test_throttled_call_retries_once_on_retry_after(no_real_sleep):
    sched = BirthdayScheduler(AsyncMock())
    sched._probe_delay = 0.0
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TelegramRetryAfter(method=_M, message="flood", retry_after=2)
        return "ok"

    result = await sched._throttled_call(flaky)

    assert result == "ok"
    assert attempts["n"] == 2               # вызов + один ретрай
    assert 2.5 in no_real_sleep             # retry_after + 0.5
