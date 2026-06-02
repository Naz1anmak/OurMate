import importlib
import os

import src.config.settings as settings_mod


def reload_settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(settings_mod)


def test_schedule_base_url_default_empty(monkeypatch):
    monkeypatch.delenv("SCHEDULE_API_BASE_URL", raising=False)
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_API_BASE_URL == ""


def test_schedule_faculty_id_default(monkeypatch):
    monkeypatch.delenv("SCHEDULE_API_FACULTY_ID", raising=False)
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_API_FACULTY_ID == 125


def test_schedule_weeks_ahead_default(monkeypatch):
    monkeypatch.delenv("SCHEDULE_API_WEEKS_AHEAD", raising=False)
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_API_WEEKS_AHEAD == 3


def test_schedule_http_timeout_default(monkeypatch):
    monkeypatch.delenv("SCHEDULE_API_HTTP_TIMEOUT", raising=False)
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_API_HTTP_TIMEOUT == 15


def test_schedule_lazy_ttl_min_default(monkeypatch):
    monkeypatch.delenv("SCHEDULE_API_LAZY_TTL_MIN", raising=False)
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_API_LAZY_TTL_MIN == 60


def test_schedule_auto_update_enabled_default(monkeypatch):
    monkeypatch.delenv("SCHEDULE_AUTO_UPDATE_ENABLED", raising=False)
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_AUTO_UPDATE_ENABLED is True


def test_schedule_group_codes_picked_up_per_code(monkeypatch):
    monkeypatch.setenv("SCHEDULE_API_GROUP_40001", "99000")
    monkeypatch.setenv("SCHEDULE_API_GROUP_40002", "99001")
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_API_GROUP_IDS == {"40001": 99000, "40002": 99001}


def test_schedule_group_ids_empty_when_none_set(monkeypatch):
    for k in list(os.environ):
        if k.startswith("SCHEDULE_API_GROUP_"):
            monkeypatch.delenv(k, raising=False)
    s = reload_settings(monkeypatch)
    assert s.SCHEDULE_API_GROUP_IDS == {}


def test_birthday_probe_delay_default(monkeypatch):
    monkeypatch.delenv("BIRTHDAY_PROBE_DELAY_SEC", raising=False)
    s = reload_settings(monkeypatch)
    assert s.BIRTHDAY_PROBE_DELAY_SEC == 0.1
