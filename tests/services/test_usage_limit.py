import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from src.bot.services.usage_limit import check_and_consume

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 6, 3, 12, 0, tzinfo=TZ)


class FakeStore:
    """Минимальный стор в памяти для юнит-тестов логики."""

    def __init__(self):
        self.data = {}

    async def get(self, scope, key, day):
        return self.data.get((scope, key, day), 0)

    async def increment(self, scope, key, day):
        self.data[(scope, key, day)] = self.data.get((scope, key, day), 0) + 1
        return self.data[(scope, key, day)]


@pytest.mark.asyncio
async def test_owner_is_never_blocked_and_not_counted():
    store = FakeStore()
    blocked = await check_and_consume(
        store, is_owner=True, is_group=True, chat_id=-100, user_id=1,
        now=NOW, pm_cap=30, chat_cap=30)
    assert blocked is False
    assert store.data == {}  # владелец не инкрементит счётчик


@pytest.mark.asyncio
async def test_pm_under_cap_allows_and_increments():
    store = FakeStore()
    blocked = await check_and_consume(
        store, is_owner=False, is_group=False, chat_id=7, user_id=7,
        now=NOW, pm_cap=30, chat_cap=30)
    assert blocked is False
    assert store.data == {("pm_user", 7, "2026-06-03"): 1}


@pytest.mark.asyncio
async def test_pm_at_cap_blocks_and_does_not_increment():
    store = FakeStore()
    store.data[("pm_user", 7, "2026-06-03")] = 30
    blocked = await check_and_consume(
        store, is_owner=False, is_group=False, chat_id=7, user_id=7,
        now=NOW, pm_cap=30, chat_cap=30)
    assert blocked is True
    assert store.data[("pm_user", 7, "2026-06-03")] == 30  # блок не считается


@pytest.mark.asyncio
async def test_group_uses_chat_scope_and_key():
    store = FakeStore()
    blocked = await check_and_consume(
        store, is_owner=False, is_group=True, chat_id=-100, user_id=7,
        now=NOW, pm_cap=30, chat_cap=30)
    assert blocked is False
    assert store.data == {("chat", -100, "2026-06-03"): 1}


@pytest.mark.asyncio
async def test_different_day_resets():
    store = FakeStore()
    store.data[("chat", -100, "2026-06-03")] = 30
    tomorrow = datetime(2026, 6, 4, 1, 0, tzinfo=TZ)
    blocked = await check_and_consume(
        store, is_owner=False, is_group=True, chat_id=-100, user_id=7,
        now=tomorrow, pm_cap=30, chat_cap=30)
    assert blocked is False
    assert store.data[("chat", -100, "2026-06-04")] == 1
