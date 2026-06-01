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


@pytest.mark.asyncio
async def test_stream_renderer_streamed_flag_false_without_feed():
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    assert r.streamed is False     # старт без feed — не стрим


@pytest.mark.asyncio
async def test_stream_renderer_group_gate_closed_buffers_without_render():
    """В группе до open_gate feed() копит в буфер, но не рендерит (болтовня не мелькает)."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    await r.feed("привет, это достаточно длинный кусок чтобы точно отрендериться")
    assert r.streamed is False                          # затвор закрыт — плейсхолдер не правился
    message.bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_renderer_group_open_gate_starts_streaming():
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    r.open_gate()                                       # тул стартовал — открываем живой стрим
    await r.feed("привет, это достаточно длинный кусок чтобы точно отрендериться")
    assert r.streamed is True


@pytest.mark.asyncio
async def test_stream_renderer_pm_streams_by_default():
    """В ЛС затвор открыт сразу — драфт стримится живьём, без ожидания старта тула."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "private"
    r = StreamRenderer(message)
    await r.feed("привет, это достаточно длинный кусок чтобы точно отрендериться")
    assert r.streamed is True


@pytest.mark.asyncio
async def test_stream_renderer_pm_discard_clears_draft():
    """В ЛС discard() гасит драфт безусловно (пустым текстом) — хвоста не остаётся."""
    from src.bot.handlers.llm_flow import StreamRenderer
    from aiogram.methods import SendMessageDraft
    message = AsyncMock()
    message.chat.type = "private"
    r = StreamRenderer(message)
    await r.discard()
    sent = message.bot.call_args.args[0]
    assert isinstance(sent, SendMessageDraft) and sent.text == ""


def test_flow_label_variants():
    from src.bot.handlers.llm_flow import _flow_label
    assert _flow_label(streamed=False, called_tools=[]) == "LLM"
    assert _flow_label(streamed=True, called_tools=[]) == "LLM stream"
    assert _flow_label(streamed=False, called_tools=["web_search"]) == "LLM; tool: web_search"
    assert _flow_label(streamed=True, called_tools=["web_search"]) == "LLM stream; tool: web_search"
    assert _flow_label(streamed=True, called_tools=["a", "b"]) == "LLM stream; tool: a, b"


@pytest.mark.asyncio
async def test_run_schedule_aware_notifies_owner_on_finalize_failure(monkeypatch):
    import src.bot.handlers.llm_flow as flow
    from src.bot.services.llm_tools import ToolLoopResult

    async def fake_stream(messages, tools, on_content_token=None):
        from src.bot.services.llm_tools import LLMReply
        return LLMReply(content="ответ")

    async def fake_loop(messages, tool_context, *, registry, llm_call, on_tool_start=None, **kwargs):
        await llm_call(messages, None)               # имитируем один вызов LLM
        return ToolLoopResult(text="ответ", called_tools=[])

    notified = {"n": 0}
    async def fake_notify(*args, **kwargs):
        notified["n"] += 1

    monkeypatch.setattr(flow, "stream_with_tools", fake_stream)
    monkeypatch.setattr(flow, "run_tool_loop", fake_loop)
    monkeypatch.setattr(flow, "notify_owner_error", fake_notify)
    monkeypatch.setattr(flow.context_service, "save_context", lambda *a, **k: None)

    message = AsyncMock()
    message.chat.type = "private"
    message.chat.id = 1
    message.from_user.id = 7
    message.from_user.username = "u"
    # finalize в ЛС шлёт message.answer — заставим упасть, плюс reply упадёт → finalize вернёт False
    message.answer.side_effect = Exception("send boom")
    message.reply.side_effect = Exception("reply boom")

    res = await flow.run_schedule_aware_response(
        message, [], "", "u", "вопрос", False, {}, registry=object())
    assert res is True
    assert notified["n"] == 1                        # владелец оповещён о сбое доставки


@pytest.mark.asyncio
async def test_suppress_text_skips_final_answer(monkeypatch):
    """suppress_text=True (тул сам отправил карточку) → финальный текст LLM не шлётся."""
    import src.bot.handlers.llm_flow as flow
    from src.bot.services.llm_tools import ToolLoopResult

    async def fake_loop(messages, tool_context, *, registry, llm_call, on_tool_start=None, **kwargs):
        return ToolLoopResult(text="", called_tools=["create_reminder"], suppress_text=True,
                              context_note="[поставлено напоминание #1]")

    saved = {}
    monkeypatch.setattr(flow, "run_tool_loop", fake_loop)
    monkeypatch.setattr(flow.context_service, "save_context",
                        lambda chat_id, q, a: saved.update(answer=a))

    message = AsyncMock()
    message.chat.type = "private"
    message.chat.id = 1
    message.from_user.id = 7
    message.from_user.username = "u"

    res = await flow.run_schedule_aware_response(
        message, [], "", "u", "напомни в 15:23 тест", False, {}, registry=object())
    assert res is True
    message.answer.assert_not_awaited()              # карточку отправил тул, дубля «готово» нет
    assert saved["answer"] == "[поставлено напоминание #1]"   # в контекст легла пометка, не пустота


@pytest.mark.asyncio
async def test_run_schedule_aware_notifies_owner_on_llm_error(monkeypatch):
    import src.bot.handlers.llm_flow as flow
    from src.bot.services.llm_service import LLMServiceError

    async def fake_loop(messages, tool_context, *, registry, llm_call, on_tool_start=None, **kwargs):
        raise LLMServiceError("llm down")

    notified = {"n": 0}
    async def fake_notify(*args, **kwargs):
        notified["n"] += 1

    monkeypatch.setattr(flow, "run_tool_loop", fake_loop)
    monkeypatch.setattr(flow, "notify_owner_error", fake_notify)

    message = AsyncMock()
    message.chat.type = "private"
    message.chat.id = 1
    message.from_user.id = 7
    message.from_user.username = "u"

    res = await flow.run_schedule_aware_response(
        message, [], "", "u", "вопрос", False, {}, registry=object())
    assert res is True
    assert notified["n"] == 1                        # владелец оповещён об ошибке LLM
