import pytest
from src.bot.services.notes_store import NotesStore
from src.bot.services import notes_tools as nt


class _FakeBot:
    def __init__(self, member_status="member"):
        self.sent = []
        self.edited = []
        self.deleted = []
        self._member_status = member_status  # для get_chat_member

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))

        class _M:
            message_id = 555
        return _M()

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edited.append((chat_id, message_id, text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def get_chat_member(self, chat_id, user_id):
        if self._member_status is None:
            raise RuntimeError("user not found")
        user = type("U", (), {"id": user_id, "username": "byid", "full_name": "Пойманный ID"})()
        return type("CM", (), {"status": self._member_status, "user": user})()


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


from src.models.user import User


def _ru(uid, name, last="", username=None):
    return User(user_id=uid, name=name, last_name=last, birthday="01.01",
                status="", username=username)


ROSTER = [_ru(1, "Иван", "Иванов", "vanya"), _ru(2, "Пётр", "Петров", None)]


@pytest.mark.asyncio
async def test_add_to_list_by_reply_user(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    ctx = _ctx(reply_user={"user_id": 7, "username": "guest"})
    res = await nt.add_to_list("Q", who="", tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 7) is True


@pytest.mark.asyncio
async def test_add_to_list_by_fullname(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    res = await nt.add_to_list("Q", who="Петров Пётр",
                               tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 2) is True


@pytest.mark.asyncio
async def test_add_to_list_by_numeric_id_verified(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    ctx = _ctx()  # _FakeBot по умолчанию отдаёт status="member"
    res = await nt.add_to_list("Q", who="1800296940",
                               tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 1800296940) is True
    # имя/ник берём из getChatMember, а не оставляем цифры
    assert (await store.members(nid))[0]["tg_name"] == "Пойманный ID"


@pytest.mark.asyncio
async def test_add_to_list_by_numeric_id_not_in_chat(store):
    await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    ctx = _ctx(bot=_FakeBot(member_status="left"))
    res = await nt.add_to_list("Q", who="999", tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "unresolved"


@pytest.mark.asyncio
async def test_add_to_list_ambiguous(store):
    await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    roster = ROSTER + [_ru(3, "Иван", "Сидоров", "ivan_s")]
    res = await nt.add_to_list("Q", who="Иван", tool_context=_ctx(), store=store, users=roster)
    assert res["ok"] is False and res["error"] == "ambiguous"


@pytest.mark.asyncio
async def test_add_to_list_unresolved(store):
    await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    res = await nt.add_to_list("Q", who="Сергей Сергеев",
                               tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "unresolved"


@pytest.mark.asyncio
async def test_add_to_list_forbidden(store):
    await store.create(chat_id=-100, title="Q", author_id=1, formal=False)  # автор — чужой
    ctx = _ctx(user_id=42, is_owner=False)
    res = await nt.add_to_list("Q", who="Петров Пётр",
                               tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "forbidden"


@pytest.mark.asyncio
async def test_add_to_list_not_found(store):
    res = await nt.add_to_list("Нет", who="Петров",
                               tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "not_found"


@pytest.mark.asyncio
async def test_remove_from_list_by_reply_user(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=7, username="guest")
    ctx = _ctx(reply_user={"user_id": 7, "username": "guest"})
    res = await nt.remove_from_list("Q", who="", tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 7) is False


@pytest.mark.asyncio
async def test_remove_from_list_by_position(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=7, username="a")
    await store.add_member(nid, user_id=8, username="b")
    res = await nt.remove_from_list("Q", who="2", tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 8) is False
    assert await store.is_member(nid, 7) is True


@pytest.mark.asyncio
async def test_remove_from_list_by_tg_name(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=7, username=None, tg_name="Пойманный ID")
    res = await nt.remove_from_list("Q", who="Пойманный ID",
                                    tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 7) is False


@pytest.mark.asyncio
async def test_remove_from_list_by_member_username(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=7, username="guest")  # нет в ростере
    res = await nt.remove_from_list("Q", who="@guest",
                                    tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 7) is False


@pytest.mark.asyncio
async def test_remove_from_list_by_fullname(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=2, username=None)  # Пётр Петров из ростера
    res = await nt.remove_from_list("Q", who="Петров Пётр",
                                    tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is True
    assert await store.is_member(nid, 2) is False


@pytest.mark.asyncio
async def test_remove_from_list_not_member(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=7, username="a")
    ctx = _ctx(reply_user={"user_id": 999, "username": "ghost"})
    res = await nt.remove_from_list("Q", who="", tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "not_member"


@pytest.mark.asyncio
async def test_remove_from_list_forbidden(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)  # чужой автор
    await store.add_member(nid, user_id=7, username="a")
    ctx = _ctx(user_id=42, is_owner=False)
    res = await nt.remove_from_list("Q", who="1", tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "forbidden"


@pytest.mark.asyncio
async def test_remove_from_list_not_found(store):
    res = await nt.remove_from_list("Нет", who="1",
                                    tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "not_found"


@pytest.mark.asyncio
async def test_add_to_list_edits_existing_card(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.set_card_message(nid, 555)  # карточка уже есть
    ctx = _ctx(reply_user={"user_id": 7, "username": "guest"})
    res = await nt.add_to_list("Q", who="", tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is True
    assert ctx["bot"].edited and not ctx["bot"].sent  # правим на месте, дубль не шлём


@pytest.mark.asyncio
async def test_show_list_replies_to_existing_card(store):
    nid = await store.create(chat_id=-100, title="Only", author_id=1, formal=False)
    await store.set_card_message(nid, 555)
    ctx = _ctx()
    res = await nt.show_list(tool_context=ctx, store=store)
    assert res["ok"] is True
    # карточку не трогаем: короткий reply на неё, без правки и без новой карточки
    assert not ctx["bot"].edited
    assert len(ctx["bot"].sent) == 1
    assert ctx["bot"].sent[0][2].get("reply_to_message_id") == 555


@pytest.mark.asyncio
async def test_add_to_list_captures_tg_name(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    ctx = _ctx(reply_user={"user_id": 7, "username": None, "name": "Александр"})
    res = await nt.add_to_list("Q", who="", tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is True
    assert (await store.members(nid))[0]["tg_name"] == "Александр"


@pytest.mark.asyncio
async def test_move_in_list_by_position(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    for uid in (1, 2, 3):
        await store.add_member(nid, user_id=uid, username=f"u{uid}")
    res = await nt.move_in_list("Q", who="3", position=1,
                                tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is True
    assert [m["user_id"] for m in await store.members(nid)] == [3, 1, 2]


@pytest.mark.asyncio
async def test_move_in_list_bad_position(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    await store.add_member(nid, user_id=1, username="a")
    res = await nt.move_in_list("Q", who="1", position=0,
                                tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "bad_position"


@pytest.mark.asyncio
async def test_move_in_list_forbidden(store):
    nid = await store.create(chat_id=-100, title="Q", author_id=1, formal=False)  # чужой автор
    await store.add_member(nid, user_id=1, username="a")
    ctx = _ctx(user_id=42, is_owner=False)
    res = await nt.move_in_list("Q", who="1", position=1, tool_context=ctx, store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "forbidden"


@pytest.mark.asyncio
async def test_move_in_list_not_member(store):
    await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    res = await nt.move_in_list("Q", who="555", position=1,
                                tool_context=_ctx(), store=store, users=ROSTER)
    assert res["ok"] is False and res["error"] == "not_member"


@pytest.mark.asyncio
async def test_delete_list_asks_confirm(store):
    await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    ctx = _ctx()
    res = await nt.delete_list("Q", tool_context=ctx, store=store)
    assert res["ok"] is True and res["_silent"] is True
    assert ctx["bot"].sent  # спросил подтверждение
    assert await store.get_by_title(-100, "Q") is not None  # ещё не удалён


@pytest.mark.asyncio
async def test_delete_list_forbidden(store):
    await store.create(chat_id=-100, title="Q", author_id=1, formal=False)
    res = await nt.delete_list("Q", tool_context=_ctx(user_id=42), store=store)
    assert res["ok"] is False and res["error"] == "forbidden"


@pytest.mark.asyncio
async def test_clear_list_asks_confirm(store):
    await store.create(chat_id=-100, title="Q", author_id=42, formal=False)
    ctx = _ctx()
    res = await nt.clear_list("Q", tool_context=ctx, store=store)
    assert res["ok"] is True and ctx["bot"].sent
