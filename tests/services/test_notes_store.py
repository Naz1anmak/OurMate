import pytest
from src.bot.services.notes_store import NotesStore


@pytest.fixture
async def store(tmp_path):
    s = NotesStore(str(tmp_path / "notes.db"))
    await s.init()
    return s


@pytest.mark.asyncio
async def test_create_and_get_by_title(store):
    nid = await store.create(chat_id=-100, title="Очередь", author_id=42, formal=False)
    assert isinstance(nid, int)
    note = await store.get_by_title(-100, "очередь")  # регистронезависимо
    assert note["id"] == nid and note["title"] == "Очередь" and note["author_id"] == 42
    assert note["formal"] == 0


@pytest.mark.asyncio
async def test_create_duplicate_title_returns_none(store):
    await store.create(chat_id=-100, title="Очередь", author_id=42, formal=False)
    dup = await store.create(chat_id=-100, title="очередь", author_id=7, formal=True)
    assert dup is None


@pytest.mark.asyncio
async def test_list_for_chat_with_counts(store):
    a = await store.create(chat_id=-100, title="A", author_id=1, formal=False)
    await store.create(chat_id=-100, title="B", author_id=1, formal=False)
    await store.add_member(a, user_id=5, username="u5")
    rows = await store.list_for_chat(-100)
    titles = {r["title"]: r for r in rows}
    assert titles["A"]["member_count"] == 1
    assert titles["B"]["member_count"] == 0


@pytest.mark.asyncio
async def test_set_formal(store):
    nid = await store.create(chat_id=-100, title="A", author_id=1, formal=False)
    assert await store.set_formal(nid, True) is True
    assert (await store.get(nid))["formal"] == 1


@pytest.mark.asyncio
async def test_members_order_is_queue(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    await store.add_member(nid, user_id=1, username="a")
    await store.add_member(nid, user_id=2, username="b")
    await store.add_member(nid, user_id=3, username="c")
    order = [m["user_id"] for m in await store.members(nid)]
    assert order == [1, 2, 3]


@pytest.mark.asyncio
async def test_add_member_idempotent(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    assert await store.add_member(nid, user_id=1, username="a") is True
    assert await store.add_member(nid, user_id=1, username="a2") is False
    assert await store.count(nid) == 1


@pytest.mark.asyncio
async def test_toggle_member(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    assert await store.toggle_member(nid, user_id=9, username="x") is True   # записан
    assert await store.is_member(nid, 9) is True
    assert await store.toggle_member(nid, user_id=9, username="x") is False  # вышел
    assert await store.is_member(nid, 9) is False


@pytest.mark.asyncio
async def test_set_note_and_name(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=True)
    await store.add_member(nid, user_id=5, username="u")
    assert await store.set_note(nid, 5, "1, 3") is True
    assert await store.set_name(nid, 5, "Иванов Иван") is True
    m = (await store.members(nid))[0]
    assert m["note"] == "1, 3" and m["name_override"] == "Иванов Иван"


@pytest.mark.asyncio
async def test_set_note_non_member_fails(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    assert await store.set_note(nid, 5, "x") is False


@pytest.mark.asyncio
async def test_remove_member(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    await store.add_member(nid, user_id=5, username="u")
    assert await store.remove_member(nid, 5) is True
    assert await store.remove_member(nid, 5) is False


@pytest.mark.asyncio
async def test_card_message_roundtrip(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    assert await store.set_card_message(nid, 777) is True
    found = await store.get_by_card_message(-100, 777)
    assert found["id"] == nid
    assert await store.get_by_card_message(-100, 999) is None
