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
