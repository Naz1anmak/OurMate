import pytest
from src.bot.services import ping_service as ps


@pytest.mark.parametrize("text,expected", [
    ("@all", True),
    ("ребята @all сбор", True),
    ("@ALL", True),
    ("@all!", True),
    ("конец@all", False),
    ("@allen", False),
    ("привет", False),
    ("", False),
])
def test_has_all_trigger(text, expected):
    assert ps.has_all_trigger(text) is expected


def test_panel_text_has_count():
    out = ps.panel_text(3)
    assert "3" in out and "@all" in out


def test_panel_keyboard_two_buttons():
    kb = ps.panel_keyboard()
    flat = [b for row in kb.inline_keyboard for b in row]
    datas = {b.callback_data for b in flat}
    assert datas == {"ping:join", "ping:leave"}


def test_build_ping_messages_mentions_and_escape():
    members = [
        {"user_id": 1, "first_name": "Аня", "username": "anya"},
        {"user_id": 2, "first_name": "<b>Зло</b>", "username": None},
    ]
    msgs = ps.build_ping_messages(members)
    assert len(msgs) == 1
    body = msgs[0]
    assert 'tg://user?id=1' in body and 'tg://user?id=2' in body
    assert "&lt;b&gt;Зло&lt;/b&gt;" in body
    # меншены разделяются запятой с пробелом
    assert "</a>, <a" in body


def test_build_ping_messages_batches():
    members = [{"user_id": i, "first_name": f"U{i}", "username": None} for i in range(120)]
    msgs = ps.build_ping_messages(members)
    assert len(msgs) == 3  # 50 + 50 + 20


def test_cooldown_cycle():
    ps.reset_cooldown()
    chat = -100
    assert ps.cooldown_remaining(chat, now=1000.0) == 0.0
    ps.mark_fired(chat, now=1000.0)
    assert ps.cooldown_remaining(chat, now=1000.0) > 0
    assert ps.cooldown_remaining(chat, now=1000.0 + 9999) == 0.0
