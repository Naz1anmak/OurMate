import pytest

from src.bot.handlers.access import (
    Audience,
    DenialReason,
    Decision,
    classify,
    resolve,
    is_public_command,
)


def _ctx(*, is_owner=False, is_group_chat=False, is_group_main=False, is_whitelisted_private=False):
    return {
        "is_owner": is_owner,
        "is_group_chat": is_group_chat,
        "is_group_main": is_group_main,
        "is_whitelisted_private": is_whitelisted_private,
    }


@pytest.mark.parametrize("text,expected", [
    ("help", Audience.EVERYONE),
    ("команды", Audience.EVERYONE),
    ("отписаться", Audience.UNSUBSCRIBE),
    ("др", Audience.PUBLIC),
    ("др 12345", Audience.PUBLIC),
    ("др @user", Audience.PUBLIC),
    ("пары", Audience.PUBLIC),
    ("пары завтра", Audience.PUBLIC),
    ("обнови расписание", Audience.PUBLIC),
    ("logs", Audience.OWNER),
    ("full logs", Audience.OWNER),
    ("проверка ссылок", Audience.OWNER),
    ("привет бот", None),
    ("", None),
])
def test_classify(text, expected):
    assert classify(text) == expected


def test_is_public_command_still_exported():
    assert is_public_command("пары") is True
    assert is_public_command("др 5") is True
    assert is_public_command("logs") is False


# EVERYONE — всегда ALLOW
def test_everyone_always_allowed():
    assert resolve(Audience.EVERYONE, _ctx()) == Decision(True, None)
    assert resolve(Audience.EVERYONE, _ctx(is_group_chat=True)).allowed is True


# OWNER
def test_owner_audience():
    assert resolve(Audience.OWNER, _ctx(is_owner=True)).allowed is True
    d = resolve(Audience.OWNER, _ctx(is_owner=False, is_group_chat=True))
    assert d == Decision(False, DenialReason.OWNER_ONLY)
    d = resolve(Audience.OWNER, _ctx(is_owner=False))  # ЛС посторонний
    assert d == Decision(False, DenialReason.OWNER_ONLY)


# UNSUBSCRIBE — ЛС + список/owner; в группе PM_ONLY
def test_unsubscribe_audience():
    assert resolve(Audience.UNSUBSCRIBE, _ctx(is_group_chat=True)) == Decision(False, DenialReason.PM_ONLY)
    assert resolve(Audience.UNSUBSCRIBE, _ctx(is_owner=True)).allowed is True
    assert resolve(Audience.UNSUBSCRIBE, _ctx(is_whitelisted_private=True)).allowed is True
    assert resolve(Audience.UNSUBSCRIBE, _ctx()) == Decision(False, DenialReason.NOT_PRIVILEGED)


# PUBLIC — основная беседа / owner-в-любой-группе / whitelisted-ЛС / owner-ЛС
def test_public_audience_group():
    assert resolve(Audience.PUBLIC, _ctx(is_group_chat=True, is_group_main=True)).allowed is True
    assert resolve(Audience.PUBLIC, _ctx(is_group_chat=True, is_owner=True)).allowed is True  # owner в чужой группе
    d = resolve(Audience.PUBLIC, _ctx(is_group_chat=True))  # чужая группа, не owner
    assert d == Decision(False, DenialReason.FOREIGN_GROUP)


def test_public_audience_pm():
    assert resolve(Audience.PUBLIC, _ctx(is_owner=True)).allowed is True
    assert resolve(Audience.PUBLIC, _ctx(is_whitelisted_private=True)).allowed is True
    assert resolve(Audience.PUBLIC, _ctx()) == Decision(False, DenialReason.NOT_PRIVILEGED)
