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
async def test_tg_name_stored_and_returned(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    await store.add_member(nid, user_id=5, username=None, tg_name="Александр")
    await store.toggle_member(nid, user_id=6, username=None, tg_name="Мария П.")
    by_id = {m["user_id"]: m for m in await store.members(nid)}
    assert by_id[5]["tg_name"] == "Александр"
    assert by_id[6]["tg_name"] == "Мария П."


@pytest.mark.asyncio
async def test_move_member_reorders(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    for uid in (1, 2, 3):
        await store.add_member(nid, user_id=uid, username=f"u{uid}")
    assert await store.move_member(nid, 3, 1) is True  # третьего — на первое место
    assert [m["user_id"] for m in await store.members(nid)] == [3, 1, 2]
    assert await store.move_member(nid, 3, 99) is True  # за пределы → в конец
    assert [m["user_id"] for m in await store.members(nid)] == [1, 2, 3]


@pytest.mark.asyncio
async def test_swap_members(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    for uid in (1, 2, 3):
        await store.add_member(nid, user_id=uid, username=f"u{uid}")
    assert await store.swap_members(nid, 1, 3) is True
    assert [m["user_id"] for m in await store.members(nid)] == [3, 2, 1]
    assert await store.swap_members(nid, 1, 999) is False  # второго нет
    assert await store.swap_members(nid, 2, 2) is False     # сам с собой


@pytest.mark.asyncio
async def test_move_member_absent(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    await store.add_member(nid, user_id=1, username="a")
    assert await store.move_member(nid, 999, 1) is False


@pytest.mark.asyncio
async def test_card_message_roundtrip(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    assert await store.set_card_message(nid, 777) is True
    found = await store.get_by_card_message(-100, 777)
    assert found["id"] == nid
    assert await store.get_by_card_message(-100, 999) is None


@pytest.mark.asyncio
async def test_delete_cascades_members(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    await store.add_member(nid, user_id=5, username="u")
    assert await store.delete(nid) is True
    assert await store.get(nid) is None
    assert await store.count(nid) == 0  # members вычищены


@pytest.mark.asyncio
async def test_clear_removes_all_members(store):
    nid = await store.create(chat_id=-1, title="Q", author_id=1, formal=False)
    await store.add_member(nid, user_id=1, username="a")
    await store.add_member(nid, user_id=2, username="b")
    assert await store.clear(nid) == 2
    assert await store.count(nid) == 0


@pytest.mark.asyncio
async def test_rename_and_conflict(store):
    a = await store.create(chat_id=-1, title="A", author_id=1, formal=False)
    await store.create(chat_id=-1, title="B", author_id=1, formal=False)
    assert await store.rename(a, "C") is True
    assert (await store.get(a))["title"] == "C"
    assert await store.rename(a, "B") is False  # конфликт UNIQUE


@pytest.mark.asyncio
async def test_remove_member_everywhere(store):
    a = await store.create(chat_id=-100, title="A", author_id=1, formal=False)
    b = await store.create(chat_id=-100, title="B", author_id=1, formal=False)
    other = await store.create(chat_id=-200, title="A", author_id=1, formal=False)
    for nid in (a, b, other):
        await store.add_member(nid, user_id=5, username="u")
    removed = await store.remove_member_everywhere(-100, 5)
    assert removed == 2
    assert await store.is_member(a, 5) is False
    assert await store.is_member(other, 5) is True  # другая беседа не тронута


@pytest.mark.asyncio
async def test_cleanup_old(store):
    fresh = await store.create(chat_id=-1, title="fresh", author_id=1, formal=False)
    old = await store.create(chat_id=-1, title="old", author_id=1, formal=False)
    await store.add_member(old, user_id=5, username="u")
    # Состарить запись напрямую в БД.
    import aiosqlite
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute("UPDATE notes SET created_at = datetime('now', '-40 days') WHERE id = ?", (old,))
        await db.commit()
    removed = await store.cleanup_old(days=30)
    assert removed == 1
    assert await store.get(old) is None
    assert await store.count(old) == 0     # members старого вычищены
    assert await store.get(fresh) is not None
