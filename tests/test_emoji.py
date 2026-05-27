from src.core.emoji import E, ALL_EMOJI


def test_check_has_unicode_and_premium_id():
    assert E.CHECK.unicode == "✅"
    assert E.CHECK.premium_id == "5427009714745517609"


def test_cross_has_unicode_and_premium_id():
    assert E.CROSS.unicode == "❌"
    assert E.CROSS.premium_id == "5465665476971471368"


def test_alarm_clock_has_unicode_and_premium_id():
    assert E.ALARM_CLOCK.unicode == "⏰"
    assert E.ALARM_CLOCK.premium_id == "5413704112220949842"


def test_alarm_clock_in_all_emoji_table():
    assert E.ALARM_CLOCK in ALL_EMOJI


def test_plus_green_and_minus_red_are_gone():
    assert not hasattr(E, "PLUS_GREEN")
    assert not hasattr(E, "MINUS_RED")
