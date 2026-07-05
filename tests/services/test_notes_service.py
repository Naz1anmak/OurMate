from src.models.user import User
from src.bot.services import notes_service as ns


def _u(uid, name, last="", username=None):
    return User(user_id=uid, name=name, last_name=last, birthday="01.01",
                status="", username=username)


ROSTER = [_u(1, "Иван", "Иванов", "vanya")]


def test_resolve_display_casual_uses_username_or_id():
    html = ns.resolve_display({"user_id": 1, "username": "vanya", "name_override": None},
                              formal=False, users=ROSTER)
    assert 'tg://user?id=1' in html and "vanya" in html


def test_resolve_display_casual_prefers_tg_name():
    html = ns.resolve_display(
        {"user_id": 5, "username": "guest", "tg_name": "Александр", "name_override": None},
        formal=False, users=ROSTER)
    assert "Александр" in html and "guest" not in html and 'tg://user?id=5' in html


def test_resolve_display_casual_falls_back_to_id():
    html = ns.resolve_display(
        {"user_id": 5, "username": None, "tg_name": None, "name_override": None},
        formal=False, users=ROSTER)
    assert ">5</a>" in html  # ни имени, ни логина — остаётся id


def test_resolve_display_formal_uses_roster_fio():
    html = ns.resolve_display({"user_id": 1, "username": "vanya", "name_override": None},
                              formal=True, users=ROSTER)
    assert "Иванов Иван" in html and 'tg://user?id=1' in html


def test_resolve_display_formal_fallback_to_override():
    html = ns.resolve_display({"user_id": 99, "username": None, "name_override": "Петров Пётр"},
                              formal=True, users=ROSTER)
    assert "Петров Пётр" in html


def test_resolve_display_formal_falls_back_to_tg_name():
    # Нет в ростере и без override, но есть имя аккаунта → показываем его, не заглушку.
    html = ns.resolve_display(
        {"user_id": 99, "username": None, "name_override": None, "tg_name": "Яна К."},
        formal=True, users=ROSTER)
    assert "Яна К." in html and "имя не указано" not in html


def test_resolve_display_formal_missing_flags_placeholder():
    html = ns.resolve_display(
        {"user_id": 99, "username": None, "name_override": None, "tg_name": None},
        formal=True, users=ROSTER)
    assert "имя не указано" in html


def test_render_card_empty_and_hint():
    note = {"id": 1, "title": "Очередь", "formal": 0}
    text = ns.render_card(note, [], users=ROSTER)
    assert "Очередь" in text and "пока никто не записался" in text.lower()
    assert "ответь на это сообщение" in text  # строка-подсказка


def test_render_card_numbered_with_notes():
    note = {"id": 1, "title": "Q", "formal": 1}
    members = [
        {"user_id": 1, "username": "vanya", "name_override": None, "note": "1, 3"},
        {"user_id": 99, "username": None, "name_override": "Петров Пётр", "note": None},
    ]
    text = ns.render_card(note, members, users=ROSTER)
    assert "1. " in text and "2. " in text
    assert "Иванов Иван" in text and "— 1, 3" in text
    assert "Петров Пётр" in text


def test_render_overview():
    notes = [{"title": "A", "member_count": 2}, {"title": "B", "member_count": 0}]
    text = ns.render_overview(notes)
    assert "A" in text and "2" in text and "B" in text


def test_render_overview_empty():
    assert "заведи список" in ns.render_overview([]).lower()


def test_can_modify():
    note = {"author_id": 42}
    assert ns.can_modify(note, user_id=42, is_owner=False) is True
    assert ns.can_modify(note, user_id=7, is_owner=True) is True
    assert ns.can_modify(note, user_id=7, is_owner=False) is False


def _cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def test_format_keyboard():
    kb = ns.format_keyboard(7)
    assert set(_cbs(kb)) == {"list:fmt:1:7", "list:fmt:0:7"}


def test_card_keyboard_no_emoji():
    kb = ns.card_keyboard(7)
    assert _cbs(kb) == ["list:join:7", "list:leave:7"]
    # На кнопках только слова — без эмодзи-символов.
    assert _labels(kb) == ["Записаться", "Выйти"]


def test_confirm_delete_keyboard():
    kb = ns.confirm_keyboard(7, "del", "keep")
    assert _cbs(kb) == ["list:del:7", "list:keep:7"]
