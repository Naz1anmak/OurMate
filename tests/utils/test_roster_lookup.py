from src.models.user import User
from src.utils.text_utils import (
    get_user_id_by_username,
    find_users_by_fullname,
    roster_full_name,
)


def _u(uid, name, last="", username=None):
    return User(user_id=uid, name=name, last_name=last, birthday="01.01",
                status="", username=username)


ROSTER = [
    _u(1, "Иван", "Иванов", "vanya"),
    _u(2, "Пётр", "Петров", None),
    _u(3, "Иван", "Сидоров", "ivan_s"),
]


def test_get_user_id_by_username():
    assert get_user_id_by_username("vanya", ROSTER) == 1
    assert get_user_id_by_username("@vanya", ROSTER) == 1   # с @
    assert get_user_id_by_username("VANYA", ROSTER) == 1    # регистр
    assert get_user_id_by_username("nope", ROSTER) is None


def test_find_users_by_fullname_unique():
    found = find_users_by_fullname("Петров Пётр", ROSTER)
    assert [u.user_id for u in found] == [2]


def test_find_users_by_fullname_partial_and_ambiguous():
    # «Иван» встречается у двух — обе записи как кандидаты.
    found = find_users_by_fullname("Иван", ROSTER)
    assert {u.user_id for u in found} == {1, 3}


def test_find_users_by_fullname_none():
    assert find_users_by_fullname("Сергей Сергеев", ROSTER) == []


def test_roster_full_name():
    assert roster_full_name(_u(1, "Иван", "Иванов")) == "Иванов Иван"
    assert roster_full_name(_u(1, "Иванов Иван", "")) == "Иванов Иван"       # last пуст
    assert roster_full_name(_u(1, "Иванов Иван", "Иванов")) == "Иванов Иван"  # без дубля
