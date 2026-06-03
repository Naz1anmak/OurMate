import pytest
from src.bot.services.web_search_tool import web_search, WEB_SEARCH_SCHEMA, build_web_search_registry


def _fake_search(payload):
    """Возвращает async-функцию, отдающую заранее заданный JSON Tavily."""
    async def _fn(query, **kwargs):
        return payload
    return _fn


@pytest.mark.asyncio
async def test_web_search_parses_answer_and_results():
    payload = {
        "answer": "Краткий ответ.",
        "results": [
            {"title": "T1", "url": "https://a.example/1", "content": "c1", "score": 0.9},
            {"title": "T2", "url": "https://a.example/2", "content": "c2", "score": 0.8},
        ],
    }
    res = await web_search("что нового", tool_context={}, search_fn=_fake_search(payload))
    assert res["error"] is None
    assert res["answer"] == "Краткий ответ."
    assert res["results"] == [
        {"title": "T1", "url": "https://a.example/1", "content": "c1"},
        {"title": "T2", "url": "https://a.example/2", "content": "c2"},
    ]


@pytest.mark.asyncio
async def test_web_search_empty_query_returns_error():
    res = await web_search("   ", tool_context={}, search_fn=_fake_search({}))
    assert res["error"] == "search_failed"
    assert res["results"] == []


@pytest.mark.asyncio
async def test_web_search_network_failure_returns_error():
    async def _boom(query, **kwargs):
        raise RuntimeError("network down")
    res = await web_search("курс доллара", tool_context={}, search_fn=_boom)
    assert res["error"] == "search_failed"
    assert res["answer"] is None
    assert res["results"] == []


def test_web_search_schema_shape():
    fn = WEB_SEARCH_SCHEMA["function"]
    assert fn["name"] == "web_search"
    assert set(fn["parameters"]["required"]) == {"query"}


def test_build_web_search_registry_has_tool_no_gate():
    reg = build_web_search_registry()
    spec = reg.get("web_search")
    assert spec is not None
    assert spec.gate is None  # доступен всем, без гейта
