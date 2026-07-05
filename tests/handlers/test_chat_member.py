"""Тесты авто-чистки пинг-листа при выходе/исключении участника."""
import pytest

from src.bot.services.ping_store import PingStore
from src.bot.services.notes_store import NotesStore
from src.bot.handlers import chat_member as cm


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _FakeUser:
    def __init__(self, uid):
        self.id = uid


class _FakeMember:
    def __init__(self, uid, status):
        self.user = _FakeUser(uid)
        self.status = status


class _FakeEvent:
    def __init__(self, chat_id, uid, status):
        self.chat = _FakeChat(chat_id)
        self.new_chat_member = _FakeMember(uid, status)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    s = PingStore(str(tmp_path / "ping.db"))
    await s.init()
    monkeypatch.setattr(cm, "ping_store", s)
    notes = NotesStore(str(tmp_path / "notes.db"))
    await notes.init()
    monkeypatch.setattr(cm, "notes_store", notes)
    return s


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["left", "kicked"])
async def test_gone_member_removed(store, status):
    await store.join(chat_id=-100, user_id=7, first_name="A", username=None)
    await cm.on_chat_member_update(_FakeEvent(-100, 7, status))
    assert await store.count(-100) == 0


@pytest.mark.asyncio
async def test_member_still_present_kept(store):
    await store.join(chat_id=-100, user_id=7, first_name="A", username=None)
    await cm.on_chat_member_update(_FakeEvent(-100, 7, "member"))
    assert await store.count(-100) == 1
