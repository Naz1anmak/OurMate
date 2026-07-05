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


def test_resolve_display_formal_uses_roster_fio():
    html = ns.resolve_display({"user_id": 1, "username": "vanya", "name_override": None},
                              formal=True, users=ROSTER)
    assert "Иванов Иван" in html and 'tg://user?id=1' in html


def test_resolve_display_formal_fallback_to_override():
    html = ns.resolve_display({"user_id": 99, "username": None, "name_override": "Петров Пётр"},
                              formal=True, users=ROSTER)
    assert "Петров Пётр" in html


def test_resolve_display_formal_missing_flags_placeholder():
    html = ns.resolve_display({"user_id": 99, "username": None, "name_override": None},
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
