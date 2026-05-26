from src.core.emoji import E, ALL_EMOJI


def test_plus_green_exists_with_premium_id():
    assert E.PLUS_GREEN.unicode == "➕"
    assert E.PLUS_GREEN.premium_id == "5226945370684140473"


def test_minus_red_exists_with_premium_id():
    assert E.MINUS_RED.unicode == "➖"
    assert E.MINUS_RED.premium_id == "5229113891081956317"


def test_new_emojis_are_in_all_emoji():
    assert E.PLUS_GREEN in ALL_EMOJI
    assert E.MINUS_RED in ALL_EMOJI
