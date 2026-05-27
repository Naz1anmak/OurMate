from src.bot.handlers.chat_context import is_public_command


def test_obnovi_raspisanie_is_public():
    assert is_public_command("обнови расписание") is True


def test_existing_public_commands_still_work():
    assert is_public_command("пары") is True
    assert is_public_command("пары завтра") is True
    assert is_public_command("др") is True
