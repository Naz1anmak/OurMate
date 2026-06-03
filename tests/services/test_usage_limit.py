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


from src.bot.services.usage_limit import enforce_usage_limit
from src.bot.handlers.usage_limit_variants import pick_limit_variant


class _FakeChat:
    def __init__(self, chat_type):
        self.type = chat_type


class FakeMessage:
    def __init__(self, chat_type):
        self.chat = _FakeChat(chat_type)
        self.replied = None
        self.answered = None

    async def reply(self, text, **kwargs):
        self.replied = text

    async def answer(self, text, **kwargs):
        self.answered = text


@pytest.mark.asyncio
async def test_enforce_blocks_with_reply_in_group(monkeypatch):
    import src.bot.services.usage_limit as ul

    async def _blocked(*a, **k):
        return True
    monkeypatch.setattr(ul, "check_and_consume", _blocked)

    msg = FakeMessage("supergroup")
    blocked = await enforce_usage_limit(
        msg, {"is_owner": False, "is_group": True, "chat_id": -100, "user_id": 7})
    assert blocked is True
    assert msg.replied is not None   # в группе — reply
    assert msg.answered is None


@pytest.mark.asyncio
async def test_enforce_blocks_with_answer_in_pm(monkeypatch):
    import src.bot.services.usage_limit as ul

    async def _blocked(*a, **k):
        return True
    monkeypatch.setattr(ul, "check_and_consume", _blocked)

    msg = FakeMessage("private")
    blocked = await enforce_usage_limit(
        msg, {"is_owner": False, "is_group": False, "chat_id": 7, "user_id": 7})
    assert blocked is True
    assert msg.answered is not None  # в ЛС — answer
    assert msg.replied is None


@pytest.mark.asyncio
async def test_enforce_allows_when_under_cap(monkeypatch):
    import src.bot.services.usage_limit as ul

    async def _ok(*a, **k):
        return False
    monkeypatch.setattr(ul, "check_and_consume", _ok)

    msg = FakeMessage("private")
    blocked = await enforce_usage_limit(
        msg, {"is_owner": False, "is_group": False, "chat_id": 7, "user_id": 7})
    assert blocked is False
    assert msg.answered is None and msg.replied is None
