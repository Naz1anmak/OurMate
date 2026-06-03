import pytest
from src.bot.services.llm_tools import ToolRegistry, ToolSpec

def _spec(name):
    async def f(*, tool_context, **kwargs):
        return {"ok": name}
    return ToolSpec(schema={"type": "function", "function": {"name": name}}, func=f)

def test_registry_register_get_and_schemas():
    reg = ToolRegistry()
    reg.register("a", _spec("a"))
    reg.register("b", _spec("b"))
    assert reg.get("a").schema["function"]["name"] == "a"
    assert reg.get("missing") is None
    names = {s["function"]["name"] for s in reg.schemas()}
    assert names == {"a", "b"}


import json
from src.bot.services.llm_tools import run_tool_loop, LLMReply, ToolRegistry, ToolSpec

def _fake_llm(replies):
    """Отдаёт LLMReply по очереди; запоминает, с какими tools вызывали."""
    calls = []
    seq = list(replies)
    async def llm_call(messages, tools):
        calls.append({"messages": list(messages), "tools": tools})
        return seq.pop(0)
    return llm_call, calls

def _tool_call(name, args: dict, tc_id="tc1"):
    return {"id": tc_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}

def _registry_with(func, name="get_schedule", gate="schedule_allowed"):
    reg = ToolRegistry()
    reg.register(name, ToolSpec(
        schema={"type": "function", "function": {"name": name}}, func=func, gate=gate))
    return reg

@pytest.mark.asyncio
async def test_chitchat_no_tool():
    llm_call, calls = _fake_llm([LLMReply(content="привет!")])
    reg = ToolRegistry()
    res = await run_tool_loop([{"role": "user", "content": "как дела"}],
                              {"schedule_allowed": True}, registry=reg, llm_call=llm_call)
    assert res.text == "привет!"
    assert res.denial is None
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_tool_executed_then_final():
    async def tool(*, tool_context, **kw):
        return {"formatted": "10:00 Предмет A", "events": []}
    reg = _registry_with(tool)
    llm_call, calls = _fake_llm([
        LLMReply(tool_calls=[_tool_call("get_schedule", {"date_from": "2026-06-01", "date_to": "2026-06-01"})],
                 reasoning_content="думаю"),
        LLMReply(content="В понедельник одна пара."),
    ])
    res = await run_tool_loop([{"role": "user", "content": "что в пн"}],
                              {"schedule_allowed": True}, registry=reg, llm_call=llm_call)
    assert res.text == "В понедельник одна пара."
    # assistant-сообщение с tool_calls должно нести reasoning_content (V4 round-trip)
    phase2_msgs = calls[1]["messages"]
    assistant = next(m for m in phase2_msgs if m["role"] == "assistant" and m.get("tool_calls"))
    assert assistant["reasoning_content"] == "думаю"
    tool_msg = next(m for m in phase2_msgs if m["role"] == "tool")
    assert "Предмет A" in tool_msg["content"]

@pytest.mark.asyncio
async def test_tool_exception_injected_not_raised():
    async def tool(*, tool_context, **kw):
        raise RuntimeError("boom")
    reg = _registry_with(tool)
    llm_call, calls = _fake_llm([
        LLMReply(tool_calls=[_tool_call("get_schedule", {"date_from": "x", "date_to": "x"})]),
        LLMReply(content="не смог достать"),
    ])
    res = await run_tool_loop([{"role": "user", "content": "?"}],
                              {"schedule_allowed": True}, registry=reg, llm_call=llm_call)
    tool_msg = next(m for m in calls[1]["messages"] if m["role"] == "tool")
    assert "error" in tool_msg["content"]
    assert res.text == "не смог достать"

@pytest.mark.asyncio
async def test_access_denied_short_circuit():
    called = {"n": 0}
    async def tool(*, tool_context, **kw):
        called["n"] += 1
        return {}
    reg = _registry_with(tool)
    llm_call, calls = _fake_llm([
        LLMReply(tool_calls=[_tool_call("get_schedule", {"date_from": "2026-06-01", "date_to": "2026-06-01"})]),
    ])
    res = await run_tool_loop([{"role": "user", "content": "что в пн"}],
                              {"schedule_allowed": False, "denial_text": "нельзя тут"},
                              registry=reg, llm_call=llm_call)
    assert res.denial == "нельзя тут"
    assert res.text is None
    assert called["n"] == 0          # тул не исполнялся
    assert len(calls) == 1           # второй фазы не было

@pytest.mark.asyncio
async def test_deferred_messages_collected():
    async def tool(*, tool_context, **kw):
        return {"formatted": "x", "_deferred": ["diff!"]}
    reg = _registry_with(tool)
    llm_call, calls = _fake_llm([
        LLMReply(tool_calls=[_tool_call("get_schedule", {"date_from": "2026-06-01", "date_to": "2026-06-01"})]),
        LLMReply(content="готово"),
    ])
    res = await run_tool_loop([{"role": "user", "content": "?"}],
                              {"schedule_allowed": True}, registry=reg, llm_call=llm_call)
    assert res.deferred_messages == ["diff!"]
    tool_msg = next(m for m in calls[1]["messages"] if m["role"] == "tool")
    assert "_deferred" not in tool_msg["content"]   # модель не видит служебное поле

@pytest.mark.asyncio
async def test_silent_flag_short_circuits_and_suppresses():
    """`_silent` тула → suppress_text и НЕТ второго вызова LLM (тул всё отправил сам)."""
    async def tool(*, tool_context, **kw):
        return {"ok": True, "_silent": True, "_context_note": "[поставлено напоминание #1]"}
    reg = _registry_with(tool)
    # Только один reply: если бы цикл пошёл в фазу-2, pop из пустого списка упал бы.
    llm_call, calls = _fake_llm([
        LLMReply(tool_calls=[_tool_call("get_schedule", {"date_from": "2026-06-01", "date_to": "2026-06-01"})]),
    ])
    res = await run_tool_loop([{"role": "user", "content": "?"}],
                              {"schedule_allowed": True}, registry=reg, llm_call=llm_call)
    assert res.suppress_text is True
    assert res.text == ""
    assert res.context_note == "[поставлено напоминание #1]"   # пометка для контекста проброшена
    assert len(calls) == 1            # второго (подтверждающего) вызова LLM не было


@pytest.mark.asyncio
async def test_silent_tool_drops_prior_deferred():
    """list_reminders (deferred) перед update_reminder (_silent) → служебный список НЕ вываливается.

    Регресс на баг «второго срабатывания» при редактировании: мутирующий тул сам шлёт карточку,
    а deferred от lookup-тула не должен дублироваться рядом списком.
    """
    async def lookup(*, tool_context, **kw):
        return {"count": 1, "_deferred": ["весь список напоминаний"]}

    async def mutate(*, tool_context, **kw):
        return {"ok": True, "_silent": True, "_context_note": "[предложена правка #1]"}

    reg = ToolRegistry()
    reg.register("list_reminders", ToolSpec(
        schema={"type": "function", "function": {"name": "list_reminders"}}, func=lookup, gate=None))
    reg.register("update_reminder", ToolSpec(
        schema={"type": "function", "function": {"name": "update_reminder"}}, func=mutate, gate=None))

    # Раунд 1 — lookup (не silent, идём дальше); раунд 2 — мутация (silent, короткозамыкание).
    llm_call, calls = _fake_llm([
        LLMReply(tool_calls=[_tool_call("list_reminders", {})]),
        LLMReply(tool_calls=[_tool_call("update_reminder", {"reminder_id": 1}, tc_id="tc2")]),
    ])
    res = await run_tool_loop([{"role": "user", "content": "перенеси напоминание на 16:00"}],
                              {}, registry=reg, llm_call=llm_call, max_tool_rounds=2)
    assert res.suppress_text is True
    assert res.deferred_messages == []     # список от list_reminders погашен, не дублируется
    assert res.called_tools == ["list_reminders", "update_reminder"]


@pytest.mark.asyncio
async def test_run_tool_loop_calls_on_tool_start():
    seen = []

    async def on_tool_start(name):
        seen.append(name)

    calls = {"n": 0}
    async def llm_call(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMReply(content="", tool_calls=[
                {"id": "c1", "function": {"name": "demo_tool", "arguments": "{}"}}])
        return LLMReply(content="финал", tool_calls=None)

    reg = ToolRegistry()
    async def _fn(*, tool_context, **kwargs):
        return {"ok": True}
    reg.register("demo_tool", ToolSpec(
        schema={"type": "function", "function": {"name": "demo_tool", "parameters": {}}},
        func=_fn, gate=None))

    res = await run_tool_loop([], {}, registry=reg,
                              llm_call=llm_call, on_tool_start=on_tool_start)
    assert seen == ["demo_tool"]
    assert res.text == "финал"
    assert res.called_tools == ["demo_tool"]


@pytest.mark.asyncio
async def test_loop_limit_forces_final():
    async def tool(*, tool_context, **kw):
        return {"error": "bad_arguments"}
    reg = _registry_with(tool)
    # модель упорно зовёт тул; после лимита (1 переспрос) делаем финальный вызов без tools
    llm_call, calls = _fake_llm([
        LLMReply(tool_calls=[_tool_call("get_schedule", {"date_from": "x", "date_to": "y"})]),
        LLMReply(tool_calls=[_tool_call("get_schedule", {"date_from": "z", "date_to": "w"}, tc_id="tc2")]),
        LLMReply(content="не понял дату, уточни"),
    ])
    res = await run_tool_loop([{"role": "user", "content": "?"}],
                              {"schedule_allowed": True}, registry=reg, llm_call=llm_call)
    assert res.text == "не понял дату, уточни"
    assert calls[-1]["tools"] is None    # финальный вызов — без тулов
