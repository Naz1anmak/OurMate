import pytest
from src.bot.services.usage_limit_store import UsageLimitStore


@pytest.fixture
async def store(tmp_path):
    s = UsageLimitStore(str(tmp_path / "usage.db"))
    await s.init()
    return s


@pytest.mark.asyncio
async def test_get_returns_zero_when_absent(store):
    assert await store.get("pm_user", 7, "2026-06-03") == 0


@pytest.mark.asyncio
async def test_increment_grows_and_returns_new_count(store):
    assert await store.increment("pm_user", 7, "2026-06-03") == 1
    assert await store.increment("pm_user", 7, "2026-06-03") == 2
    assert await store.get("pm_user", 7, "2026-06-03") == 2


@pytest.mark.asyncio
async def test_keys_and_scopes_independent(store):
    await store.increment("pm_user", 7, "2026-06-03")
    await store.increment("chat", 7, "2026-06-03")      # тот же key, другой scope
    await store.increment("pm_user", 8, "2026-06-03")   # другой key
    assert await store.get("pm_user", 7, "2026-06-03") == 1
    assert await store.get("chat", 7, "2026-06-03") == 1
    assert await store.get("pm_user", 8, "2026-06-03") == 1


@pytest.mark.asyncio
async def test_day_separates_counters(store):
    await store.increment("chat", -100, "2026-06-03")
    assert await store.get("chat", -100, "2026-06-04") == 0


@pytest.mark.asyncio
async def test_persist_across_connections(store):
    await store.increment("pm_user", 7, "2026-06-03")
    # новый инстанс на тот же файл — данные на диске, не в памяти процесса
    reopened = UsageLimitStore(store.db_path)
    assert await reopened.get("pm_user", 7, "2026-06-03") == 1


@pytest.mark.asyncio
async def test_cleanup_old_removes_stale_rows(store):
    from datetime import date, timedelta
    old_day = (date.today() - timedelta(days=40)).isoformat()   # старше порога → под снос
    fresh_day = (date.today() - timedelta(days=1)).isoformat()  # свежая → остаётся
    await store.increment("chat", -100, old_day)
    await store.increment("chat", -100, fresh_day)
    removed = await store.cleanup_old(days=30)
    assert removed == 1
    assert await store.get("chat", -100, old_day) == 0
    assert await store.get("chat", -100, fresh_day) == 1
