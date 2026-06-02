from unittest.mock import AsyncMock
import pytest

import src.bot.scheduler.birthday_scheduler as bsched
from src.bot.scheduler.birthday_scheduler import BirthdayScheduler
from src.bot.services.birthday_service import birthday_service
from src.models.user import User, DmState
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiohttp import ClientOSError
from aiogram.methods import SendChatAction

_M = SendChatAction(chat_id=1, action="typing")


def _user(uid, **kw) -> User:
    d = {"name": f"U{uid}", "birthday": "1.1", "user_id": uid}
    d.update(kw)
    return User.from_dict(d)


@pytest.fixture
def patched(monkeypatch):
    async def fake_sleep(_):
        return None
    monkeypatch.setattr(bsched.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(birthday_service, "save_users", lambda: None)
    monkeypatch.setattr(bsched, "_load_active_snapshot", lambda: {})
    monkeypatch.setattr(bsched, "_save_active_snapshot", lambda users: None)


async def test_classifies_each_outcome(patched, monkeypatch, caplog):
    users = [
        _user(1),  # успех -> reachable
        _user(2),  # blocked
        _user(3),  # never_started
        _user(4),  # deactivated
        _user(5),  # network -> не трогаем
    ]
    monkeypatch.setattr(birthday_service, "users", users)

    bot = AsyncMock()
    bot.send_chat_action = AsyncMock(side_effect=[
        None,
        TelegramForbiddenError(method=_M, message="Forbidden: bot was blocked by the user"),
        TelegramForbiddenError(method=_M, message="Forbidden: bot can't initiate conversation with a user"),
        TelegramBadRequest(method=_M, message="Bad Request: chat not found"),
        ClientOSError("network"),
    ])
    sched = BirthdayScheduler(bot)

    with caplog.at_level("INFO"):
        await sched._refresh_access_flags()

    assert users[0].dm_state == DmState.REACHABLE
    assert users[1].dm_state == DmState.BLOCKED
    assert users[2].dm_state == DmState.NEVER_STARTED
    assert users[3].dm_state == DmState.DEACTIVATED
    assert users[4].dm_state == DmState.UNKNOWN  # сеть — не трогаем
    log = "\n".join(r.message for r in caplog.records)
    assert "забанили: 1" in log
    assert "не начали диалог: 1" in log
    assert "удалён/нет чата: 1" in log
    assert "сетевых: 1" in log


async def test_probe_success_does_not_resurrect_unsubscribed(patched, monkeypatch):
    u = _user(7, dm_state="unknown", subscribed=False)  # отписался ранее
    monkeypatch.setattr(birthday_service, "users", [u])
    bot = AsyncMock()
    bot.send_chat_action = AsyncMock(return_value=None)  # пинг успешен
    sched = BirthdayScheduler(bot)

    await sched._refresh_access_flags()

    assert u.dm_state == DmState.REACHABLE
    assert u.subscribed is False
    assert u.is_active is False  # отписка сохранена
