import pytest
from src.bot.services.notes_store import NotesStore
from src.bot.handlers import notes_reply as nr
from src.bot.handlers import notes_callbacks as nc


async def _noop(*a, **kw):
    return None


class _ReplyTo:
    def __init__(self, message_id):
        self.message_id = message_id


class _Msg:
    def __init__(self, text, reply_to_id, chat_id=-100, uid=7):
        self.text = text
        self.reply_to_message = _ReplyTo(reply_to_id)
        self.chat = type("C", (), {"id": chat_id})()
        self.from_user = type("U", (), {"id": uid, "username": "u"})()
        self.replies = []

    async def reply(self, text, **kw):
        self.replies.append(text)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    s = NotesStore(str(tmp_path / "notes.db"))
    await s.init()
    monkeypatch.setattr(nr, "notes_store", s)
    monkeypatch.setattr(nc, "notes_store", s)
    monkeypatch.setattr(nr, "_rerender_from_message", _noop)
    nc._pending_name.clear()
    return s


@pytest.mark.asyncio
async def test_reply_sets_note_for_member(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    await store.set_card_message(nid, 555)
    await store.add_member(nid, user_id=7, username="u")
    msg = _Msg("1, 3", reply_to_id=555, uid=7)
    assert await nr.handle_notes_reply(msg) is True
    assert (await store.members(nid))[0]["note"] == "1, 3"


@pytest.mark.asyncio
async def test_reply_dash_clears_note(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    await store.set_card_message(nid, 555)
    await store.add_member(nid, user_id=7, username="u")
    await store.set_note(nid, 7, "1, 3")
    msg = _Msg("-", reply_to_id=555, uid=7)  # «-» убирает уточнение
    assert await nr.handle_notes_reply(msg) is True
    assert (await store.members(nid))[0]["note"] == ""


@pytest.mark.asyncio
async def test_reply_phrase_is_kept_as_note(store):
    # Глаголы-команды убраны: «удали …» — это обычный текст уточнения, не очистка.
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    await store.set_card_message(nid, 555)
    await store.add_member(nid, user_id=7, username="u")
    await store.set_note(nid, 7, "1, 3")
    msg = _Msg("удали моё уточнение", reply_to_id=555, uid=7)
    assert await nr.handle_notes_reply(msg) is True
    assert (await store.members(nid))[0]["note"] == "удали моё уточнение"


@pytest.mark.asyncio
async def test_reply_non_member_prompts_join(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    await store.set_card_message(nid, 555)
    msg = _Msg("1, 3", reply_to_id=555, uid=999)  # не участник
    assert await nr.handle_notes_reply(msg) is True
    assert msg.replies  # подсказка «сначала запишись»


@pytest.mark.asyncio
async def test_reply_sets_name_via_pending(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=True)
    await store.add_member(nid, user_id=7, username=None)
    nc._pending_name[(-100, 900)] = (nid, 7)
    msg = _Msg("Иванов Иван", reply_to_id=900, uid=7)
    assert await nr.handle_notes_reply(msg) is True
    assert (await store.members(nid))[0]["name_override"] == "Иванов Иван"
    assert (-100, 900) not in nc._pending_name  # запрос закрыт


@pytest.mark.asyncio
async def test_reply_to_unknown_message_ignored(store):
    msg = _Msg("что-то", reply_to_id=12345)
    assert await nr.handle_notes_reply(msg) is False
