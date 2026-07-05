import pytest
from src.bot.services.notes_store import NotesStore
from src.bot.handlers import notes_callbacks as nc


class _Msg:
    def __init__(self, chat_id=-100, message_id=555):
        self.chat = type("C", (), {"id": chat_id})()
        self.message_id = message_id
        self.edited = []
        self.answers = []

    async def edit_text(self, text, **kw):
        self.edited.append((text, kw))

    async def answer(self, text, **kw):
        self.answers.append((text, kw))

        class _M:
            message_id = 900
        return _M()


class _Query:
    def __init__(self, data, uid=7, username="u", first_name="Аня", message=None):
        self.data = data
        self.message = message or _Msg()
        self.from_user = type("U", (), {"id": uid, "username": username,
                                        "first_name": first_name,
                                        "full_name": first_name})()
        self.toasts = []

    async def answer(self, text="", **kw):
        self.toasts.append(text)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    s = NotesStore(str(tmp_path / "notes.db"))
    await s.init()
    monkeypatch.setattr(nc, "notes_store", s)
    nc._pending_name.clear()
    return s


@pytest.mark.asyncio
async def test_fmt_turns_picker_into_card(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.set_card_message(nid, 555)
    q = _Query(f"list:fmt:1:{nid}", uid=42, message=_Msg(message_id=555))
    await nc.on_notes_callback(q)
    assert (await store.get(nid))["formal"] == 1
    assert q.message.edited  # превратилось в карточку


@pytest.mark.asyncio
async def test_join_and_leave(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    q = _Query(f"list:join:{nid}", uid=7)
    await nc.on_notes_callback(q)
    assert await store.is_member(nid, 7) is True
    q2 = _Query(f"list:leave:{nid}", uid=7)
    await nc.on_notes_callback(q2)
    assert await store.is_member(nid, 7) is False


@pytest.mark.asyncio
async def test_join_formal_missing_name_requests_forcereply(store, monkeypatch):
    # Ростер пуст → user 777 не в ростере.
    monkeypatch.setattr(nc.birthday_service, "users", [])
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=True)
    q = _Query(f"list:join:{nid}", uid=777, username=None)
    await nc.on_notes_callback(q)
    assert await store.is_member(nid, 777) is True
    assert nc._pending_name  # запрос имени зарегистрирован


@pytest.mark.asyncio
async def test_del_confirm_removes(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    q = _Query(f"list:del:{nid}", uid=42)  # автор
    await nc.on_notes_callback(q)
    assert await store.get(nid) is None


@pytest.mark.asyncio
async def test_clr_confirm_clears(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=1, username="a")
    q = _Query(f"list:clr:{nid}", uid=42)  # автор
    await nc.on_notes_callback(q)
    assert await store.count(nid) == 0


@pytest.mark.asyncio
async def test_del_non_author_rejected(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    q = _Query(f"list:del:{nid}", uid=7)  # не автор и не владелец
    await nc.on_notes_callback(q)
    assert await store.get(nid) is not None  # список не тронут
    assert q.toasts and "автор" in q.toasts[0].lower()


@pytest.mark.asyncio
async def test_clr_non_author_rejected(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=1, username="a")
    q = _Query(f"list:clr:{nid}", uid=7)  # не автор и не владелец
    await nc.on_notes_callback(q)
    assert await store.count(nid) == 1  # участники не тронуты


@pytest.mark.asyncio
async def test_fmt_non_author_rejected(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.set_card_message(nid, 555)
    q = _Query(f"list:fmt:1:{nid}", uid=7, message=_Msg(message_id=555))
    await nc.on_notes_callback(q)
    assert (await store.get(nid))["formal"] == 0  # формат не изменён
