import pytest
from src.bot.services.notes_store import NotesStore
from src.bot.services import notes_tools as nt


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))

        class _M:
            message_id = 555
        return _M()


@pytest.fixture
async def store(tmp_path):
    s = NotesStore(str(tmp_path / "notes.db"))
    await s.init()
    return s


def _ctx(**kw):
    base = {"bot": _FakeBot(), "chat_id": -100, "user_id": 42, "username": "boss",
            "is_group": True, "is_group_main": True, "is_owner": False,
            "reply_user": None, "mentioned_users": []}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_create_list_posts_format_picker(store):
    ctx = _ctx()
    res = await nt.create_list("Очередь", tool_context=ctx, store=store)
    assert res["ok"] is True and res["_silent"] is True
    note = await store.get_by_title(-100, "Очередь")
    assert note is not None and note["card_message_id"] == 555  # picker стал карточкой
    assert ctx["bot"].sent  # сообщение-выбор отправлено


@pytest.mark.asyncio
async def test_create_list_foreign_group(store):
    ctx = _ctx(is_group_main=False)
    res = await nt.create_list("Q", tool_context=ctx, store=store)
    assert res == {"ok": False, "error": "foreign_group"}


@pytest.mark.asyncio
async def test_create_list_duplicate(store):
    await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    ctx = _ctx()
    res = await nt.create_list("q", tool_context=ctx, store=store)
    assert res["ok"] is False and res["error"] == "exists"


@pytest.mark.asyncio
async def test_show_list_ambiguous(store):
    await store.create(chat_id=-100, title="A", author_id=1, formal=False)
    await store.create(chat_id=-100, title="B", author_id=1, formal=False)
    res = await nt.show_list(tool_context=_ctx(), store=store)  # без title, >1
    assert res["ok"] is False and res["error"] == "ambiguous"
    assert set(res["titles"]) == {"A", "B"}


@pytest.mark.asyncio
async def test_show_list_single(store):
    await store.create(chat_id=-100, title="Only", author_id=1, formal=False)
    ctx = _ctx()
    res = await nt.show_list(tool_context=ctx, store=store)
    assert res["ok"] is True and res["_silent"] is True
    assert ctx["bot"].sent  # карточка отправлена
