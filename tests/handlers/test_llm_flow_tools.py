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
