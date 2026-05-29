import pytest
from datetime import date
from src.bot.services.schedule_tools import validate_date_range

def test_valid_single_day():
    ok, value = validate_date_range("2026-06-01", "2026-06-01", max_days=28)
    assert ok is True
    assert value == (date(2026, 6, 1), date(2026, 6, 1))

def test_from_after_to():
    ok, value = validate_date_range("2026-06-02", "2026-06-01", max_days=28)
    assert ok is False
    assert value["error"] == "bad_range"

def test_bad_iso():
    ok, value = validate_date_range("01.06.2026", "2026-06-01", max_days=28)
    assert ok is False
    assert value["error"] == "bad_range"

def test_range_too_wide():
    ok, value = validate_date_range("2026-06-01", "2026-09-01", max_days=28)
    assert ok is False
    assert value["error"] == "bad_range"
