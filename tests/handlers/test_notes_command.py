import pytest
from src.bot.services.notes_store import NotesStore
from src.bot.handlers import chat_commands as cc


class _Msg:
    def __init__(self, chat_id=-100):
        self.chat = type("C", (), {"id": chat_id, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": 1, "username": "u", "full_name": "U"})()
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append((text, kw))


@pytest.fixture
async def store(tmp_path, monkeypatch):
    s = NotesStore(str(tmp_path / "notes.db"))
    await s.init()
    monkeypatch.setattr(cc, "notes_store", s)
    return s


@pytest.mark.asyncio
async def test_lists_command_overview(store):
    await store.create(chat_id=-100, title="Очередь", author_id=1, formal=False)
    msg = _Msg()
    await cc.handle_lists_command(msg)
    assert msg.answers
    assert "Очередь" in msg.answers[0][0]


@pytest.mark.asyncio
async def test_lists_command_empty(store):
    msg = _Msg()
    await cc.handle_lists_command(msg)
    assert "заведи список" in msg.answers[0][0].lower()
