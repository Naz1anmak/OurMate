import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from src.bot.services.web_search_tool import web_search

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 5, 30, 9, 0, tzinfo=TZ)


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
    res = await web_search("что нового", tool_context={}, search_fn=_fake_search(payload),
                           now=NOW, daily_cap=200)
    assert res["error"] is None
    assert res["answer"] == "Краткий ответ."
    assert res["results"] == [
        {"title": "T1", "url": "https://a.example/1", "content": "c1"},
        {"title": "T2", "url": "https://a.example/2", "content": "c2"},
    ]
