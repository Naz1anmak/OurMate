import pytest

from src.bot.services.birthday_service import BirthdayService
from src.models.user import User, DmState


def _u(uid, **kw):
    d = {"name": f"U{uid}", "birthday": "1.1", "user_id": uid}
    d.update(kw)
    return User.from_dict(d)


def test_split_uses_is_active(monkeypatch):
    svc = BirthdayService()
    active = _u(1, dm_state="reachable", subscribed=True)
    blocked = _u(2, dm_state="blocked", subscribed=True)
    optout = _u(3, dm_state="reachable", subscribed=False)
    svc.users = [active, blocked, optout]

    # подменяем LLM, чтобы не ходить в сеть
    monkeypatch.setattr(
        "src.bot.services.birthday_service.LLMService.send_birthday_request",
        staticmethod(lambda prompt: "поздравляю"),
    )
    messages, not_interacted = svc.generate_birthday_messages([active, blocked, optout])

    assert {u.user_id for u in not_interacted} == {2, 3}  # blocked и отписавшийся — не активны
    assert len(messages) == 1  # только active получает поздравление
