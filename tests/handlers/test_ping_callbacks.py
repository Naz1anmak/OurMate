"""Smoke-тесты колбэков пинг-панели: join/leave + обновление счётчика."""
import pytest

from src.bot.services.ping_store import PingStore
from src.bot.handlers import ping_callbacks as cb


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _FakeMessage:
    def __init__(self, chat_id):
        self.chat = _FakeChat(chat_id)
        self.edits = []

    async def edit_text(self, text, **kw):
        self.edits.append((text, kw))


class _FakeUser:
    def __init__(self, uid, first_name="Аня", username="anya"):
        self.id = uid
        self.first_name = first_name
        self.username = username


class _FakeQuery:
    def __init__(self, data, user_id, chat_id):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage(chat_id)
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


@pytest.fixture
async def store(tmp_path, monkeypatch):
    s = PingStore(str(tmp_path / "ping.db"))
    await s.init()
    monkeypatch.setattr(cb, "ping_store", s)
    return s


@pytest.mark.asyncio
async def test_join_then_leave(store):
    q = _FakeQuery("ping:join", user_id=7, chat_id=-100)
    await cb.on_ping_callback(q)
    assert await store.count(-100) == 1
    assert q.message.edits and "1" in q.message.edits[-1][0]
    assert q.answers[-1][0]  # был тост

    q2 = _FakeQuery("ping:leave", user_id=7, chat_id=-100)
    await cb.on_ping_callback(q2)
    assert await store.count(-100) == 0
    assert "0" in q2.message.edits[-1][0]


@pytest.mark.asyncio
async def test_leave_when_absent_is_friendly(store):
    q = _FakeQuery("ping:leave", user_id=7, chat_id=-100)
    await cb.on_ping_callback(q)
    assert await store.count(-100) == 0
    assert q.answers[-1][0]  # дружелюбный тост, без исключений


@pytest.mark.asyncio
async def test_bad_data_ignored(store):
    q = _FakeQuery("ping:bogus", user_id=7, chat_id=-100)
    await cb.on_ping_callback(q)
    assert await store.count(-100) == 0
    assert q.answers  # ответили на callback (без alert)
