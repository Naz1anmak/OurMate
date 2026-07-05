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
