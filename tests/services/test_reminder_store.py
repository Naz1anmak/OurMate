import pytest
from src.bot.services.reminder_store import ReminderStore


@pytest.fixture
async def store(tmp_path):
    s = ReminderStore(str(tmp_path / "rem.db"))
    await s.init()
    return s


@pytest.mark.asyncio
async def test_add_and_get(store):
    rid = await store.add(text="созвон", fire_at="2026-06-05T18:00:00+03:00",
                          scope="chat", chat_id=-100, author_id=42)
    row = await store.get(rid)
    assert row["text"] == "созвон"
    assert row["scope"] == "chat"
    assert row["author_id"] == 42
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_subscriber_unique_and_toggle(store):
    rid = await store.add(text="t", fire_at="2026-06-05T18:00:00+03:00",
                          scope="chat", chat_id=-100, author_id=1)
    assert await store.toggle_subscriber(rid, user_id=7, first_name="Аня", username="anya") is True
    assert await store.count_subscribers(rid) == 1
    # повторный toggle снимает подписку
    assert await store.toggle_subscriber(rid, user_id=7, first_name="Аня", username="anya") is False
    assert await store.count_subscribers(rid) == 0


@pytest.mark.asyncio
async def test_cancel_cascades_subscribers(store):
    rid = await store.add(text="t", fire_at="2026-06-05T18:00:00+03:00",
                          scope="chat", chat_id=-100, author_id=1)
    await store.toggle_subscriber(rid, user_id=7, first_name="Аня", username=None)
    await store.set_status(rid, "cancelled")
    # подписчики удаляются каскадом
    assert await store.count_subscribers(rid) == 0


@pytest.mark.asyncio
async def test_list_pending_for_chat(store):
    a = await store.add(text="a", fire_at="2026-06-05T18:00:00+03:00",
                        scope="chat", chat_id=-100, author_id=1)
    await store.add(text="b", fire_at="2026-06-06T18:00:00+03:00",
                    scope="chat", chat_id=-999, author_id=1)
    await store.set_status(a, "fired")
    rows = await store.list_pending_for_chat(-100)
    assert rows == []  # a выстрелил, b в другом чате
    rows2 = await store.list_pending_for_chat(-999)
    assert len(rows2) == 1 and rows2[0]["text"] == "b"


@pytest.mark.asyncio
async def test_apply_pending_update(store):
    rid = await store.add(text="старый", fire_at="2026-06-05T18:00:00+03:00",
                          scope="chat", chat_id=-100, author_id=1)
    await store.set_pending_update(rid, text="новый", fire_at="2026-06-05T19:00:00+03:00")
    row = await store.get(rid)
    assert row["pending_text"] == "новый"
    await store.apply_pending_update(rid)
    row2 = await store.get(rid)
    assert row2["text"] == "новый"
    assert row2["fire_at"] == "2026-06-05T19:00:00+03:00"
    assert row2["pending_text"] is None and row2["pending_fire_at"] is None


@pytest.mark.asyncio
async def test_cleanup_old_removes_terminal_keeps_pending(store):
    keep = await store.add(text="живой", fire_at="2026-06-05T18:00:00+03:00",
                           scope="chat", chat_id=-100, author_id=1)
    old_fired = await store.add(text="старый", fire_at="2026-06-05T18:00:00+03:00",
                                scope="chat", chat_id=-100, author_id=1)
    await store.set_status(old_fired, "fired")
    old_draft = await store.add(text="черновик", fire_at="2026-06-05T18:00:00+03:00",
                                scope="self", chat_id=1, author_id=1, status="draft")
    # Состарим created_at у всех записей — pending должен пережить чистку по статусу.
    async with store._db() as db:
        await store._setup(db)
        await db.execute("UPDATE reminders SET created_at = datetime('now', '-30 days')")
        await db.commit()
    removed = await store.cleanup_old(days=7)
    assert removed == 2                              # fired + draft
    assert await store.get(keep) is not None         # pending жив несмотря на возраст
    assert await store.get(old_fired) is None
    assert await store.get(old_draft) is None
