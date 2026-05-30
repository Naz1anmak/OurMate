import pytest
from unittest.mock import AsyncMock
from src.bot.handlers.llm_flow import (
    send_tool_loop_extras,
    _inject_system_note,
    SCHEDULE_PRESENTATION_NOTE,
)


def test_inject_system_note_after_leading_system_messages():
    messages = [
        {"role": "system", "content": "персона"},
        {"role": "system", "content": "контекст времени"},
        {"role": "user", "content": "что в субботу?"},
    ]
    out = _inject_system_note(messages, SCHEDULE_PRESENTATION_NOTE)
    assert len(messages) == 3  # исходный список не мутирован
    assert len(out) == 4
    assert out[2] == {"role": "system", "content": SCHEDULE_PRESENTATION_NOTE}
    assert out[3]["role"] == "user"

@pytest.mark.asyncio
async def test_send_deferred_messages_after_answer():
    message = AsyncMock()
    await send_tool_loop_extras(message, deferred_messages=["diff1", "diff2"], denial=None)
    assert message.answer.await_count == 2
    message.answer.assert_any_await("diff1", parse_mode="HTML")

@pytest.mark.asyncio
async def test_send_denial_stub():
    message = AsyncMock()
    await send_tool_loop_extras(message, deferred_messages=[], denial="нельзя")
    message.answer.assert_awaited_once_with("нельзя", parse_mode="HTML")

@pytest.mark.asyncio
async def test_stream_renderer_pm_finalize_sends_message():
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "private"
    r = StreamRenderer(message)
    await r.start("ожидаю…")          # в ЛС плейсхолдер не шлётся
    message.reply.assert_not_awaited()
    await r.feed("привет ")            # копит в буфер
    await r.feed("мир")
    ok = await r.finalize("привет мир")
    assert ok is True
    message.answer.assert_awaited()    # финал — реальное сообщение (драфт эфемерен)


@pytest.mark.asyncio
async def test_stream_renderer_tool_indicator_group_edits_placeholder():
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")           # в группе создаётся плейсхолдер
    message.bot.edit_message_text.reset_mock()
    await r.show_tool_indicator("web_search")
    message.bot.edit_message_text.assert_awaited()   # индикатор показан через edit


@pytest.mark.asyncio
async def test_stream_renderer_tool_indicator_pm_noop():
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "private"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    await r.show_tool_indicator("web_search")
    message.bot.edit_message_text.assert_not_awaited()  # в ЛС индикатора нет


@pytest.mark.asyncio
async def test_stream_renderer_tool_indicator_unknown_tool_noop():
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    await r.show_tool_indicator("get_schedule")          # без индикатора
    message.bot.edit_message_text.assert_not_awaited()


def test_web_search_note_mentions_trigger_and_sources():
    from src.bot.handlers.llm_flow import WEB_SEARCH_NOTE
    note = WEB_SEARCH_NOTE.lower()
    assert "загугли" in note            # явный триггер описан
    assert "источник" in note           # политика ссылок описана
