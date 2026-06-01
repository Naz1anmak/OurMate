import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from src.bot.services.reminder_store import ReminderStore
from src.bot.services import reminder_tools as rt

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 6, 1, 9, 0, tzinfo=TZ)


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))

        class _M:
            message_id = 555
        return _M()


class _FakeScheduler:
    def __init__(self):
        self.scheduled = []

    def schedule(self, rid, fire_at):
        self.scheduled.append((rid, fire_at))

    def unschedule(self, rid):
        self.scheduled = [s for s in self.scheduled if s[0] != rid]


@pytest.fixture
async def store(tmp_path):
    s = ReminderStore(str(tmp_path / "rem.db"))
    await s.init()
    return s


def _ctx(**kw):
    base = {"bot": _FakeBot(), "chat_id": -100, "user_id": 42, "first_name": "Аня",
            "is_group": True, "is_group_main": True, "is_owner": False}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_create_in_group_posts_card_and_schedules(store):
    sched = _FakeScheduler()
    ctx = _ctx()
    res = await rt.create_reminder(
        "2026-06-01T19:00:00+03:00", "созвон",
        tool_context=ctx, store=store, scheduler=sched, now=NOW)
    assert res["ok"] is True
    # карточка отправлена в группу
    assert ctx["bot"].sent and ctx["bot"].sent[0][0] == -100
    # job поставлен
    assert sched.scheduled and sched.scheduled[0][1] == "2026-06-01T19:00:00+03:00"
    rows = await store.list_pending_for_chat(-100)
    assert len(rows) == 1 and rows[0]["card_message_id"] == 555


@pytest.mark.asyncio
async def test_create_in_pm_is_draft_no_schedule(store):
    sched = _FakeScheduler()
    ctx = _ctx(is_group=False, chat_id=42, user_id=42)
    res = await rt.create_reminder(
        "2026-06-02T10:00:00+03:00", "позвонить",
        tool_context=ctx, store=store, scheduler=sched, now=NOW)
    assert res["ok"] is True
    assert sched.scheduled == []          # черновик не планируется
    assert ctx["bot"].sent                # подтверждение отправлено
    # в pending пусто (черновик), но запись есть
    assert await store.list_pending_for_author(42) == []


@pytest.mark.asyncio
async def test_create_rejects_past(store):
    res = await rt.create_reminder(
        "2026-05-30T10:00:00+03:00", "вчера",
        tool_context=_ctx(), store=store, scheduler=_FakeScheduler(), now=NOW)
    assert res["ok"] is False and res["error"] == "past"


@pytest.mark.asyncio
async def test_create_rejected_in_foreign_group(store):
    # Не основная беседа → групповое напоминание не создаётся.
    ctx = _ctx(is_group=True, is_group_main=False)
    res = await rt.create_reminder(
        "2026-06-02T10:00:00+03:00", "созвон",
        tool_context=ctx, store=store, scheduler=_FakeScheduler(), now=NOW)
    assert res["ok"] is False and res["error"] == "foreign_group"
    assert await store.list_pending_for_chat(-100) == []


@pytest.mark.asyncio
async def test_create_normalizes_naive_datetime(store):
    # LLM отдал время без TZ — не должно падать, локализуется в TIMEZONE.
    sched = _FakeScheduler()
    res = await rt.create_reminder(
        "2026-06-01T19:00:00", "созвон",  # naive
        tool_context=_ctx(), store=store, scheduler=sched, now=NOW)
    assert res["ok"] is True
    rows = await store.list_pending_for_chat(-100)
    assert "+03:00" in rows[0]["fire_at"]  # сохранено уже с TZ


@pytest.mark.asyncio
async def test_list_reminders_returns_ids_and_deferred(store):
    await store.add(text="созвон", fire_at="2026-06-01T19:00:00+03:00",
                    scope="chat", chat_id=-100, author_id=42)
    res = await rt.list_reminders(tool_context=_ctx(), store=store, now=NOW)
    assert res["count"] == 1
    assert res["reminders"][0]["id"]                 # id виден LLM
    assert any("Созвон" in d or "созвон" in d for d in res["_deferred"])


@pytest.mark.asyncio
async def test_cancel_forbidden_for_stranger(store):
    rid = await store.add(text="t", fire_at="2026-06-02T10:00:00+03:00",
                          scope="chat", chat_id=-100, author_id=999)
    res = await rt.cancel_reminder(rid, tool_context=_ctx(user_id=42, is_owner=False),
                                   store=store, scheduler=_FakeScheduler(), now=NOW)
    assert res["ok"] is False and res["error"] == "forbidden"
