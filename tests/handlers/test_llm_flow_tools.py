import pytest
from unittest.mock import AsyncMock
from src.bot.handlers.llm_flow import (
    send_tool_loop_extras,
    _inject_system_note,
    SCHEDULE_PRESENTATION_NOTE,
)


@pytest.fixture(autouse=True)
def _disable_usage_limit(monkeypatch):
    """Гейт лимита прозрачен: эти тесты про тул-флоу, не про лимиты (и чтобы не писать в data/usage.db)."""
    async def _never_block(message, tool_context):
        return False
    monkeypatch.setattr("src.bot.handlers.llm_flow.enforce_usage_limit", _never_block)


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
async def test_stream_renderer_group_streams_immediately():
    """В группе первый рендер идёт сразу, как набран min_chars, без ожидания таймера."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    await r.feed("привет, " + "х" * 300)      # символов больше min_chars
    assert r.streamed is True
    message.bot.edit_message_text.assert_awaited()


@pytest.mark.asyncio
async def test_stream_renderer_pm_streams_immediately():
    """В ЛС стрим идёт драфтом с первого же feed (грейса больше нет)."""
    from src.bot.handlers.llm_flow import StreamRenderer
    from aiogram.methods import SendMessageDraft
    message = AsyncMock()
    message.chat.type = "private"
    r = StreamRenderer(message)
    await r.feed("привет, это достаточно длинный кусок чтобы точно отрендериться")
    assert r.streamed is True
    sent = message.bot.call_args.args[0]
    assert isinstance(sent, SendMessageDraft) and sent.text


@pytest.mark.asyncio
async def test_stream_renderer_reset_buffer_drops_pretool_chatter():
    """reset_buffer на старте тула сбрасывает буфер на префикс — болтовня раунда 1 не
    примешается к пост-тульному ответу второго раунда."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message, prefix="Имя, ")
    await r.start("ожидаю…")
    await r.feed("сейчас гляну...")
    r.reset_buffer()
    assert r.buffer == r.prefix == "Имя, "
    assert r.last_sent_len == len(r.prefix)


@pytest.mark.asyncio
async def test_stream_renderer_pm_discard_clears_only_if_streamed():
    """В ЛС discard() гасит драфт пустым текстом, только если драфт реально открывали."""
    from src.bot.handlers.llm_flow import StreamRenderer
    from aiogram.methods import SendMessageDraft
    message = AsyncMock()
    message.chat.type = "private"
    r = StreamRenderer(message)
    r.streamed = True                                    # драфт был показан
    await r.discard()
    sent = message.bot.call_args.args[0]
    assert isinstance(sent, SendMessageDraft) and sent.text == ""


@pytest.mark.asyncio
async def test_stream_renderer_pm_discard_noop_when_not_streamed():
    """Грейс не дал открыть драфт (streamed=False) → discard НЕ шлёт пустой draft (иначе он прилетит пузырём)."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "private"
    r = StreamRenderer(message)                          # streamed=False, ничего не рисовали
    await r.discard()
    message.bot.assert_not_awaited()                     # пустой SendMessageDraft не отправлен


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


@pytest.mark.asyncio
async def test_stream_renderer_group_respects_time_floor():
    """Порог по символам не отменяет поле по времени: подряд идущие feed'ы не флудят эдитами."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    for _ in range(20):
        await r.feed("х" * 299 + " ")   # символов с запасом, но время не прошло
    assert message.bot.edit_message_text.await_count == 1


@pytest.mark.asyncio
async def test_stream_renderer_group_waits_for_min_chars():
    """Прошедшего времени мало: пока не набрано min_chars, эдита нет."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    r.last_flush = 0.0                 # время как будто давно прошло
    await r.feed("коротко")
    message.bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_falls_back_to_new_message_on_flood():
    """Флуд-контроль на эдите не должен съедать ответ: финал уходит новым сообщением."""
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import EditMessageText
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.side_effect = TelegramRetryAfter(
        method=EditMessageText(chat_id=1, message_id=1, text="x"), message="flood", retry_after=41)
    ok = await r.finalize("готовый ответ")
    assert ok is True
    message.reply.assert_awaited()


@pytest.mark.asyncio
async def test_stream_renderer_short_answer_is_not_throttled():
    """Короткий ответ укладывается в минутный бюджет целиком — рисуем часто, окно не мешает."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    clock = [0.0]
    r._now = lambda: clock[0]
    for _ in range(6):                       # ~1000 символов за ~15 с генерации
        clock[0] += 2.5
        await r.feed("х" * 169 + " ")
    assert message.bot.edit_message_text.await_count == 6


@pytest.mark.asyncio
async def test_stream_renderer_long_answer_hits_budget_cap():
    """Длинный ответ упирается в бюджет окна: эдиты прекращаются, буфер продолжает копиться."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    clock = [0.0]
    r._now = lambda: clock[0]
    for _ in range(30):                      # ~4500 символов, всё в пределах одной минуты
        clock[0] += 1.5
        await r.feed("х" * 169 + " ")
    assert message.bot.edit_message_text.await_count == r.EDIT_BUDGET_PER_MIN
    assert len(r.buffer) > 4000              # буфер копится, ничего не теряем


@pytest.mark.asyncio
async def test_stream_renderer_budget_frees_after_window():
    """Окно скользящее: когда старые эдиты выпадают из минуты, стрим оживает."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    clock = [0.0]
    r._now = lambda: clock[0]
    for _ in range(30):
        clock[0] += 1.5
        await r.feed("х" * 169 + " ")
    spent = message.bot.edit_message_text.await_count
    clock[0] += 61                           # минута прошла, окно очистилось
    await r.feed("х" * 169 + " ")
    assert message.bot.edit_message_text.await_count == spent + 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("готово **жирн", "готово"),                      # незакрытый bold откушен целиком
        ("готово **жирное** дальше", "готово **жирное**"),  # закрытый bold цел, режется лишь слово
        ("текст `код", "текст"),                          # незакрытый inline-code
        ("текст ```py\nx = 1", "текст"),                  # незакрытый fence
        ("текст _кур", "текст"),                          # незакрытый italic
        ("обычное сло", "обычное"),                       # половина слова
        ("обычное слово ", "обычное слово"),              # хвост уже на границе
    ],
)
def test_stream_safe_prefix_cuts_unfinished_markup(raw, expected):
    from src.bot.handlers.llm_flow import _stream_safe_prefix
    assert _stream_safe_prefix(raw) == expected


@pytest.mark.asyncio
async def test_stream_frame_has_no_dangling_markers():
    """В кадр стрима не должны попадать голые ** от ещё не закрытого жирного."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    message.bot.edit_message_text.reset_mock()
    await r.feed("х" * 150 + " начало **жирного")
    sent = message.bot.edit_message_text.await_args.kwargs["text"]
    assert "**" not in sent and sent.endswith("начало")


@pytest.mark.asyncio
async def test_stream_skips_frame_when_growth_is_all_unclosed():
    """Если весь прирост — незакрытая разметка, кадр не тратит бюджет эдитов."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    clock = [0.0]
    r._now = lambda: clock[0]
    clock[0] += 5
    await r.feed("х" * 150 + " конец ")        # кадр показан целиком, придержанного хвоста нет
    message.bot.edit_message_text.reset_mock()
    spent = len(r._edits)
    clock[0] += 5
    await r.feed(" **" + "ж" * 200)                # прирост целиком внутри незакрытого bold
    message.bot.edit_message_text.assert_not_awaited()
    assert len(r._edits) == spent


@pytest.mark.asyncio
async def test_finalize_keeps_full_text():
    """Финал отрисовывается целиком: обрезка хвоста — только для промежуточных кадров."""
    from src.bot.handlers.llm_flow import StreamRenderer
    message = AsyncMock()
    message.chat.type = "supergroup"
    r = StreamRenderer(message)
    await r.start("ожидаю…")
    await r.finalize("итог **жирным** и хвост")
    sent = message.bot.edit_message_text.await_args.kwargs["text"]
    assert "<b>жирным</b>" in sent and sent.endswith("хвост")
