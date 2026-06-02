from src.models.user import User, DmState


def _base(**kw) -> dict:
    data = {"name": "Иван Иванов", "birthday": "1.1"}
    data.update(kw)
    return data


def test_defaults_for_minimal_entry():
    u = User.from_dict(_base())
    assert u.dm_state == DmState.UNKNOWN
    assert u.subscribed is True
    assert u.is_active is False  # UNKNOWN != REACHABLE


def test_is_active_requires_reachable_and_subscribed():
    u = User.from_dict(_base())
    u.dm_state = DmState.REACHABLE
    u.subscribed = True
    assert u.is_active is True
    u.subscribed = False
    assert u.is_active is False
    u.subscribed = True
    u.dm_state = DmState.BLOCKED
    assert u.is_active is False


def test_migration_old_true():
    u = User.from_dict(_base(interacted_with_bot=True))
    assert u.dm_state == DmState.REACHABLE
    assert u.subscribed is True
    assert u.is_active is True


def test_migration_old_false_preserves_optout():
    u = User.from_dict(_base(interacted_with_bot=False))
    assert u.dm_state == DmState.UNKNOWN
    assert u.subscribed is False
    assert u.is_active is False


def test_new_format_roundtrip_drops_legacy_flag():
    u = User.from_dict(_base(dm_state="blocked", subscribed=True, user_id=10))
    assert u.dm_state == DmState.BLOCKED
    d = u.to_dict()
    assert d["dm_state"] == "blocked"
    assert d["subscribed"] is True
    assert "interacted_with_bot" not in d


def test_unknown_dm_state_value_falls_back():
    u = User.from_dict(_base(dm_state="garbage"))
    assert u.dm_state == DmState.UNKNOWN
