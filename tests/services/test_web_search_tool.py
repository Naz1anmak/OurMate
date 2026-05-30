import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from src.bot.services.web_search_tool import web_search
import src.bot.services.web_search_tool as wst

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


@pytest.mark.asyncio
async def test_web_search_empty_query_returns_error():
    res = await web_search("   ", tool_context={}, search_fn=_fake_search({}),
                           now=NOW, daily_cap=200)
    assert res["error"] == "search_failed"
    assert res["results"] == []


@pytest.mark.asyncio
async def test_web_search_network_failure_returns_error():
    async def _boom(query, **kwargs):
        raise RuntimeError("network down")
    res = await web_search("курс доллара", tool_context={}, search_fn=_boom,
                           now=NOW, daily_cap=200)
    assert res["error"] == "search_failed"
    assert res["answer"] is None
    assert res["results"] == []


@pytest.mark.asyncio
async def test_web_search_quota_exhausted():
    wst._usage["date"] = None  # сброс состояния перед тестом
    payload = {"answer": "ok", "results": []}
    r1 = await web_search("q1", tool_context={}, search_fn=_fake_search(payload), now=NOW, daily_cap=2)
    r2 = await web_search("q2", tool_context={}, search_fn=_fake_search(payload), now=NOW, daily_cap=2)
    r3 = await web_search("q3", tool_context={}, search_fn=_fake_search(payload), now=NOW, daily_cap=2)
    assert r1["error"] is None and r2["error"] is None
    assert r3["error"] == "quota_exhausted"
    assert r3["results"] == []


@pytest.mark.asyncio
async def test_web_search_quota_resets_next_day():
    wst._usage["date"] = None
    payload = {"answer": "ok", "results": []}
    await web_search("q1", tool_context={}, search_fn=_fake_search(payload), now=NOW, daily_cap=1)
    blocked = await web_search("q2", tool_context={}, search_fn=_fake_search(payload), now=NOW, daily_cap=1)
    assert blocked["error"] == "quota_exhausted"
    tomorrow = NOW + timedelta(days=1)
    ok = await web_search("q3", tool_context={}, search_fn=_fake_search(payload), now=tomorrow, daily_cap=1)
    assert ok["error"] is None
