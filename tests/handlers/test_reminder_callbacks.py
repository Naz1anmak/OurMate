"""Smoke-тесты callback'ов напоминаний: sub/ok/del/upd, проверка прав."""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from src.bot.services.reminder_store import ReminderStore
from src.bot.handlers import reminder_callbacks as cb

TZ = ZoneInfo("Europe/Moscow")
FIRE_AT = "2026-06-10T10:00:00+03:00"

# ID, которые гарантированно не совпадут с реальным OWNER_CHAT_ID
AUTHOR_ID = 42
STRANGER_ID = 999
SENTINEL_OWNER_ID = 0  # монкипатчим модуль этим значением


class _FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kw):
        self.edits.append((text, kw))


class _FakeUser:
    def __init__(self, uid, first_name="Аня", username="anya"):
        self.id = uid
        self.first_name = first_name
        self.username = username


class _FakeQuery:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage()
        self.bot = None  # _refresh_card нужен только для scope=chat, в тестах scope=self/chat
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class _FakeScheduler:
    def __init__(self):
        self.scheduled = []
        self.unscheduled = []

    def schedule(self, rid, fire_at):
        self.scheduled.append((rid, fire_at))

    def unschedule(self, rid):
        self.unscheduled.append(rid)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    s = ReminderStore(str(tmp_path / "rem.db"))
    await s.init()
    monkeypatch.setattr("src.bot.handlers.reminder_callbacks.reminder_store", s)
    return s


@pytest.fixture
def sched(monkeypatch):
    sc = _FakeScheduler()
    monkeypatch.setattr(cb, "scheduler", sc)
    return sc


@pytest.fixture(autouse=True)
def pin_owner(monkeypatch):
    """Фиксируем OWNER_CHAT_ID в модуле, чтобы тестовые ID не случайно совпали."""
    monkeypatch.setattr(cb, "OWNER_CHAT_ID", SENTINEL_OWNER_ID)


# ── 1. sub toggle ──────────────────────────────────────────────────────────────

async def test_sub_subscribe_then_unsubscribe(store, sched):
    rid = await store.add(
        text="созвон", fire_at=FIRE_AT,
        scope="chat", chat_id=-100, author_id=AUTHOR_ID)

    # Первый клик → подписан
    q1 = _FakeQuery(f"rem:sub:{rid}", AUTHOR_ID)
    await cb.on_reminder_callback(q1)
    assert await store.count_subscribers(rid) == 1
    assert q1.answers == [("Вы подписаны на напоминание", False)]

    # Второй клик → отписан
    q2 = _FakeQuery(f"rem:sub:{rid}", AUTHOR_ID)
    await cb.on_reminder_callback(q2)
    assert await store.count_subscribers(rid) == 0
    assert q2.answers == [("Вы отписаны от напоминания", False)]


# ── 2. ok — подтверждение черновика ───────────────────────────────────────────

async def test_ok_confirms_draft(store, sched):
    rid = await store.add(
        text="встреча", fire_at=FIRE_AT,
        scope="self", chat_id=AUTHOR_ID, author_id=AUTHOR_ID,
        status="draft")

    q = _FakeQuery(f"rem:ok:{rid}", AUTHOR_ID)
    await cb.on_reminder_callback(q)

    fresh = await store.get(rid)
    assert fresh["status"] == "pending"
    assert sched.scheduled == [(rid, FIRE_AT)]
    assert q.answers == [("Готово", False)]


# ── 3. del — отмена автором ───────────────────────────────────────────────────

async def test_del_by_author_cancels(store, sched):
    rid = await store.add(
        text="купить молоко", fire_at=FIRE_AT,
        scope="self", chat_id=AUTHOR_ID, author_id=AUTHOR_ID)

    q = _FakeQuery(f"rem:del:{rid}", AUTHOR_ID)
    await cb.on_reminder_callback(q)

    fresh = await store.get(rid)
    assert fresh["status"] == "cancelled"
    assert rid in sched.unscheduled
    assert q.answers == [("Отменено", False)]


# ── 4. del — запрет для постороннего ─────────────────────────────────────────

async def test_del_forbidden_for_stranger(store, sched):
    rid = await store.add(
        text="чужое напоминание", fire_at=FIRE_AT,
        scope="chat", chat_id=-100, author_id=AUTHOR_ID)

    q = _FakeQuery(f"rem:del:{rid}", STRANGER_ID)
    await cb.on_reminder_callback(q)

    fresh = await store.get(rid)
    assert fresh["status"] == "pending"       # не отменено
    assert rid not in sched.unscheduled       # unschedule не вызван
    # answer с show_alert=True
    assert any(show for _, show in q.answers)


# ── 5. upd на черновике промоутит в pending (регресс Fix 2) ──────────────────

async def test_upd_on_draft_promotes_to_pending(store, sched):
    rid = await store.add(
        text="старый текст", fire_at=FIRE_AT,
        scope="self", chat_id=AUTHOR_ID, author_id=AUTHOR_ID,
        status="draft")
    # Устанавливаем отложенную правку (новое время)
    new_fire_at = "2026-06-11T12:00:00+03:00"
    await store.set_pending_update(rid, text=None, fire_at=new_fire_at)

    q = _FakeQuery(f"rem:upd:{rid}", AUTHOR_ID)
    await cb.on_reminder_callback(q)

    fresh = await store.get(rid)
    assert fresh["status"] == "pending"           # был draft — стал pending
    assert fresh["fire_at"] == new_fire_at        # правка применена
    assert sched.scheduled == [(rid, new_fire_at)]
    assert q.answers == [("Обновлено", False)]


# ── 6. подписка на сработавшее напоминание не проходит ───────────────────────

async def test_sub_on_fired_is_rejected(store, sched):
    rid = await store.add(
        text="прошедшее", fire_at=FIRE_AT,
        scope="chat", chat_id=-100, author_id=AUTHOR_ID)
    await store.set_status(rid, "fired")

    q = _FakeQuery(f"rem:sub:{rid}", STRANGER_ID)
    await cb.on_reminder_callback(q)

    assert await store.count_subscribers(rid) == 0          # не подписан
    assert q.answers == [("Это событие уже прошло", False)]  # осмысленный тост
