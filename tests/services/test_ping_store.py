import pytest
from src.bot.services.ping_store import PingStore


@pytest.fixture
async def store(tmp_path):
    s = PingStore(str(tmp_path / "ping.db"))
    await s.init()
    return s


@pytest.mark.asyncio
async def test_join_count_and_list(store):
    await store.join(chat_id=-100, user_id=7, first_name="Аня", username="anya")
    assert await store.count(-100) == 1
    rows = await store.list_members(-100)
    assert rows[0]["user_id"] == 7 and rows[0]["first_name"] == "Аня"


@pytest.mark.asyncio
async def test_join_is_idempotent_and_updates_name(store):
    await store.join(chat_id=-100, user_id=7, first_name="Аня", username="anya")
    await store.join(chat_id=-100, user_id=7, first_name="Анна", username="anna")
    assert await store.count(-100) == 1
    rows = await store.list_members(-100)
    assert rows[0]["first_name"] == "Анна" and rows[0]["username"] == "anna"


@pytest.mark.asyncio
async def test_leave(store):
    await store.join(chat_id=-100, user_id=7, first_name="Аня", username=None)
    assert await store.leave(-100, 7) is True
    assert await store.count(-100) == 0
    assert await store.leave(-100, 7) is False


@pytest.mark.asyncio
async def test_scoped_by_chat(store):
    await store.join(chat_id=-100, user_id=7, first_name="A", username=None)
    await store.join(chat_id=-200, user_id=7, first_name="A", username=None)
    assert await store.count(-100) == 1
    assert await store.count(-200) == 1
    await store.leave(-100, 7)
    assert await store.count(-100) == 0
    assert await store.count(-200) == 1


@pytest.mark.asyncio
async def test_is_member(store):
    assert await store.is_member(-100, 7) is False
    await store.join(chat_id=-100, user_id=7, first_name="A", username=None)
    assert await store.is_member(-100, 7) is True
