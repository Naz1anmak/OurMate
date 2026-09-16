import pytest
from unittest.mock import AsyncMock

import src.bot.handlers.llm_flow as flow
from src.bot.handlers.llm_flow import (
    VOICE_MARKER,
    detect_voice_marker,
    should_send_voice,
    strip_voice_marker,
    strip_voice_tags,
)


@pytest.fixture(autouse=True)
def _disable_usage_limit(monkeypatch):
    async def _never_block(message, tool_context):
        return False
    monkeypatch.setattr("src.bot.handlers.llm_flow.enforce_usage_limit", _never_block)


LONG = "Ребят, учебный год начался, какой ещё Китай, сессию сначала закройте"


@pytest.mark.parametrize("raw, expected", [
    ("[voice]\nпривет", (True, "привет")),
    ("  [voice] привет", (True, "привет")),
    ("привет", (False, "привет")),
    ("текст [voice] в середине", (False, "текст [voice] в середине")),
])
def test_strip_voice_marker(raw, expected):
    assert strip_voice_marker(raw) == expected


def test_strip_voice_tags():
    assert strip_voice_tags("Ну (sighs) ладно <#0.5#> иди (laughs)") == "Ну ладно иди"
    assert strip_voice_tags("пара (ауд. 101) в 10:00") == "пара (ауд. 101) в 10:00"


@pytest.mark.parametrize("buf, expected", [
    ("", None), ("[vo", None), ("  [voi", None),
    ("[voice]", True), ("[voice] привет", True),
    ("[ссылка]", False), ("привет", False),
])
def test_detect_voice_marker(buf, expected):
    assert detect_voice_marker(buf) is expected


def _ctx(**kw):
    base = {"is_owner": False, "is_whitelisted_private": False}
    base.update(kw)
    return base


@pytest.fixture
def voice_on(monkeypatch):
    monkeypatch.setattr(flow, "is_voice_enabled", lambda: True)
    monkeypatch.setattr(flow, "VOICE_MIN_CHARS", 35)


def test_should_send_voice_group_ok(voice_on):
    assert should_send_voice(is_voice=True, text=LONG, called_tools=[],
                             tool_context=_ctx(), is_group_chat=True) is True


def test_should_send_voice_length_boundary(voice_on):
    kw = dict(is_voice=True, called_tools=[], tool_context=_ctx(), is_group_chat=True)
    assert should_send_voice(text="а" * 34, **kw) is False
    assert should_send_voice(text="а" * 35, **kw) is True
    # теги не засчитываются в длину
    assert should_send_voice(text="а" * 30 + " (laughs)", **kw) is False


def test_should_send_voice_pm_access(voice_on):
    kw = dict(is_voice=True, text=LONG, called_tools=[], is_group_chat=False)
    assert should_send_voice(tool_context=_ctx(), **kw) is False
    assert should_send_voice(tool_context=_ctx(is_whitelisted_private=True), **kw) is True
    assert should_send_voice(tool_context=_ctx(is_owner=True), **kw) is True


def test_should_send_voice_blockers(voice_on, monkeypatch):
    kw = dict(text=LONG, tool_context=_ctx(), is_group_chat=True)
    assert should_send_voice(is_voice=False, called_tools=[], **kw) is False
    assert should_send_voice(is_voice=True, called_tools=["web_search"], **kw) is False
    monkeypatch.setattr(flow, "is_voice_enabled", lambda: False)
    assert should_send_voice(is_voice=True, called_tools=[], **kw) is False


def test_voice_note_mentions_marker_without_sound_tags():
    assert VOICE_MARKER in flow.VOICE_NOTE
    assert "<#0.5#>" in flow.VOICE_NOTE
    assert "(laughs)" not in flow.VOICE_NOTE


class FakeSender:
    """Подмена ChatActionSender: фиксирует старт/стоп без фоновой задачи."""
    instances: list = []

    def __init__(self, *, bot, chat_id, action, **kw):
        self.action = action
        self.entered = False
        self.exited = False
        FakeSender.instances.append(self)

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.exited = True


@pytest.fixture
def fake_sender(monkeypatch):
    FakeSender.instances = []
    monkeypatch.setattr(flow, "ChatActionSender", FakeSender)
    return FakeSender


def _renderer(chat_type, **kw):
    message = AsyncMock()
    message.chat.type = chat_type
    message.chat.id = 1
    r = flow.StreamRenderer(message, **kw)
    r.min_interval = 0
    r.min_chars = 1
    return message, r


async def test_group_voice_marker_split_tokens(fake_sender):
    message, r = _renderer("supergroup", detect_voice=True)
    await r.start("Думаю…")
    message.bot.edit_message_text.reset_mock()
    await r.feed("[vo")
    assert r.voice_mode is None
    await r.feed("ice]\nНу привет, как дела у вас там")
    assert r.voice_mode is True
    message.bot.edit_message_text.assert_not_awaited()     # стрим не рисуется
    message.bot.delete_message.assert_awaited()             # «Думаю…» удалено
    assert fake_sender.instances[0].action == "record_voice"
    assert fake_sender.instances[0].entered


async def test_pm_voice_marker_no_draft(fake_sender):
    message, r = _renderer("private", detect_voice=True)
    await r.start("…")
    await r.feed("[voice] Ну привет, как дела у вас там, всё норм")
    assert r.voice_mode is True
    message.bot.assert_not_awaited()                        # ни одного SendMessageDraft
    assert r.streamed is False


async def test_bracket_text_is_not_voice(fake_sender):
    message, r = _renderer("supergroup", detect_voice=True)
    await r.start("Думаю…")
    message.bot.edit_message_text.reset_mock()
    await r.feed("[ссылка] и дальше обычный длинный ответ")
    assert r.voice_mode is False
    message.bot.edit_message_text.assert_awaited()          # обычный стрим
    assert fake_sender.instances == []


async def test_detect_disabled_streams_as_before(fake_sender):
    message, r = _renderer("supergroup")                    # detect_voice=False по умолчанию
    await r.start("Думаю…")
    message.bot.edit_message_text.reset_mock()
    await r.feed("[voice] привет всем тут")
    message.bot.edit_message_text.assert_awaited()
    assert fake_sender.instances == []


async def test_reset_buffer_resets_voice_mode(fake_sender):
    _, r = _renderer("supergroup", detect_voice=True)
    await r.start("Думаю…")
    await r.feed("[voice] ща гляну")
    assert r.voice_mode is True
    r.reset_buffer()
    assert r.voice_mode is None


async def test_finalize_stops_voice_action(fake_sender):
    message, r = _renderer("supergroup", detect_voice=True)
    await r.start("Думаю…")
    await r.feed("[voice] Ну привет, как дела у вас там")
    await r.finalize("текстовый фолбэк")
    assert fake_sender.instances[0].exited
    message.reply.assert_awaited()                          # плейсхолдера нет → reply


from src.bot.services.llm_tools import ToolLoopResult
from src.bot.services.tts_service import TTSServiceError


def _flow_message(chat_type):
    message = AsyncMock()
    message.chat.type = chat_type
    message.chat.id = 1
    message.from_user.id = 7
    message.from_user.username = "u"
    return message


def _patch_flow(monkeypatch, text, *, called_tools=None, synth=None):
    async def fake_loop(messages, tool_context, *, registry, llm_call, on_tool_start=None, **kw):
        return ToolLoopResult(text=text, called_tools=called_tools or [])

    async def ok_synth(t):
        return b"OggS"

    saved, notified = {}, {"n": 0}

    async def fake_notify(*a, **k):
        notified["n"] += 1

    monkeypatch.setattr(flow, "run_tool_loop", fake_loop)
    monkeypatch.setattr(flow, "synthesize_voice", synth or ok_synth)
    monkeypatch.setattr(flow, "notify_owner_error", fake_notify)
    monkeypatch.setattr(flow, "is_voice_enabled", lambda: True)
    monkeypatch.setattr(flow, "ChatActionSender", FakeSender)
    monkeypatch.setattr(flow.context_service, "save_context",
                        lambda chat_id, q, a: saved.update(answer=a))
    return saved, notified


async def test_flow_group_sends_voice(monkeypatch):
    saved, notified = _patch_flow(monkeypatch, f"[voice]\n{LONG} (laughs)")
    message = _flow_message("supergroup")
    await flow.run_schedule_aware_response(message, [], "", "u", "q", False, {}, registry=object())
    message.reply_voice.assert_awaited_once()
    assert message.reply_voice.await_args.args[0].data == b"OggS"
    message.bot.edit_message_text.assert_not_awaited()      # текстового финала нет
    message.bot.delete_message.assert_awaited()             # «Думаю…» убрано
    assert saved["answer"] == f"{LONG} (laughs)"            # в контексте без маркера
    assert notified["n"] == 0


async def test_flow_pm_whitelisted_sends_voice(monkeypatch):
    _patch_flow(monkeypatch, f"[voice] {LONG}")
    message = _flow_message("private")
    await flow.run_schedule_aware_response(message, [], "", "u", "q", False,
                                           {"is_whitelisted_private": True}, registry=object())
    message.answer_voice.assert_awaited_once()


async def test_flow_pm_stranger_gets_text(monkeypatch):
    _patch_flow(monkeypatch, f"[voice] {LONG} (sighs)")
    message = _flow_message("private")
    await flow.run_schedule_aware_response(message, [], "", "u", "q", False, {}, registry=object())
    message.answer_voice.assert_not_awaited()
    sent = message.answer.await_args.args[0]
    assert "[voice]" not in sent and "(sighs)" not in sent


async def test_flow_tts_error_falls_back_to_text(monkeypatch):
    async def boom(t):
        raise TTSServiceError("minimax down")

    _, notified = _patch_flow(monkeypatch, f"[voice] {LONG}", synth=boom)
    message = _flow_message("supergroup")
    await flow.run_schedule_aware_response(message, [], "", "u", "q", False, {}, registry=object())
    message.reply_voice.assert_not_awaited()
    message.reply.assert_awaited()                          # текстовый фолбэк
    assert notified["n"] == 1


async def test_flow_voice_forbidden_pm_no_owner_notify(monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    _, notified = _patch_flow(monkeypatch, f"[voice] {LONG}")
    message = _flow_message("private")
    message.answer_voice.side_effect = TelegramBadRequest(
        method=AsyncMock(), message="Bad Request: VOICE_MESSAGES_FORBIDDEN")
    await flow.run_schedule_aware_response(message, [], "", "u", "q", False,
                                           {"is_owner": True}, registry=object())
    message.answer.assert_awaited()                         # текстом
    assert notified["n"] == 0


async def test_flow_voice_marker_with_tools_goes_text(monkeypatch):
    _patch_flow(monkeypatch, f"[voice] {LONG}", called_tools=["web_search"])
    message = _flow_message("supergroup")
    await flow.run_schedule_aware_response(message, [], "", "u", "q", False, {}, registry=object())
    message.reply_voice.assert_not_awaited()


def test_flow_label_voice():
    assert flow._flow_label(streamed=False, called_tools=[], voice=True) == "LLM voice"
